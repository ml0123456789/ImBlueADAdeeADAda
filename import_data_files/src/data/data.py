"""Build and validate the harmonized bike-share trip dataset."""

from __future__ import annotations

import glob
import logging
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

_LOG = logging.getLogger(__name__)

_REQUIRED = (
    "ride_id",
    "started_at",
    "ended_at",
    "start_station_name",
    "start_station_id",
    "end_station_name",
    "end_station_id",
    "member_casual",
)

_COLUMN_ALIASES: dict[str, str] = {
    "trip_id": "ride_id",
    "01 - rental details rental id": "ride_id",
    "rental id": "ride_id",
    "starttime": "started_at",
    "start_time": "started_at",
    "01 - rental details local start time": "started_at",
    "stoptime": "ended_at",
    "end_time": "ended_at",
    "01 - rental details local end time": "ended_at",
    "from_station_name": "start_station_name",
    "03 - rental start station name": "start_station_name",
    "from_station_id": "start_station_id",
    "03 - rental start station id": "start_station_id",
    "to_station_name": "end_station_name",
    "02 - rental end station name": "end_station_name",
    "to_station_id": "end_station_id",
    "02 - rental end station id": "end_station_id",
    "usertype": "member_casual",
    "user type": "member_casual",
}

_TIMESTAMP_SQL = """
COALESCE(
    try_strptime(CAST({column} AS VARCHAR),
        ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M',
         '%m/%d/%Y %H:%M:%S', '%m/%d/%Y %H:%M']),
    TRY_CAST({column} AS TIMESTAMP)
)
"""


def standardize_pre_2020(df: pd.DataFrame, path: str) -> pd.DataFrame:
    """Map historical headers to the unified schema.

    Args:
        df: Historical CSV data.
        path: Source path, included in validation errors.

    Raises:
        ValueError: If a required field has no recognized source header.
    """
    normalized = {column: _COLUMN_ALIASES.get(column.strip().lower(), column)
                  for column in df.columns}
    df = df.rename(columns=normalized)
    missing = sorted(set(_REQUIRED) - set(df.columns))
    if missing:
        raise ValueError(
            f"{path}: no column for {missing}; found columns {list(df.columns)}"
        )
    return df


def _member_case_sql(expression: str) -> str:
    """Return a strict mapping for known historical and current user labels."""
    return f"""
        CASE
            WHEN lower(trim(CAST({expression} AS VARCHAR))) IN
                 ('subscriber', 'member') THEN 'member'
            WHEN lower(trim(CAST({expression} AS VARCHAR))) IN
                 ('customer', 'casual') THEN 'casual'
            ELSE NULL
        END
    """


def _discover_csvs(data_dir: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """Classify CSVs by header rather than relying on OS-specific folders."""
    pre_files: list[Path] = []
    post_files: list[Path] = []
    station_files: list[Path] = []
    for path in sorted(data_dir.rglob("*.csv")):
        if "__MACOSX" in path.parts or path.name.startswith("._"):
            continue
        try:
            columns = {str(c).strip().lower()
                       for c in pd.read_csv(path, nrows=0).columns}
        except Exception as exc:
            raise ValueError(f"Could not read CSV header: {path}: {exc}") from exc

        if {"ride_id", "started_at", "ended_at"}.issubset(columns):
            post_files.append(path)
        elif ("trip_id" in columns or
              "01 - rental details rental id" in columns or
              "rental id" in columns):
            pre_files.append(path)
        elif {"id", "latitude", "longitude"}.issubset(columns):
            station_files.append(path)
        else:
            raise ValueError(
                f"Unrecognized CSV header in {path}. "
                f"Found columns: {sorted(columns)}"
            )
    return pre_files, post_files, station_files


def _create_station_table(con: duckdb.DuckDBPyConnection,
                          station_files: list[Path]) -> None:
    """Choose one repeatable coordinate record per station ID."""
    con.execute("""
        CREATE OR REPLACE TABLE master_stations (
            id VARCHAR, latitude DOUBLE, longitude DOUBLE
        )
    """)
    for path in station_files:
        # Bind the path rather than interpolating it into SQL.
        con.execute("""
            INSERT INTO master_stations
            SELECT trim(CAST(id AS VARCHAR)),
                   try_cast(latitude AS DOUBLE),
                   try_cast(longitude AS DOUBLE)
            FROM read_csv(?, union_by_name = true, all_varchar = true)
            WHERE id IS NOT NULL AND latitude IS NOT NULL
        """, [str(path)])
    con.execute("""
        CREATE OR REPLACE TABLE master_stations AS
        SELECT id, latitude, longitude
        FROM (
            SELECT *, row_number() OVER (
                PARTITION BY trim(id)
                ORDER BY latitude, longitude
            ) AS row_num
            FROM master_stations
        )
        WHERE row_num = 1
    """)


def _append_pre_2020(con: duckdb.DuckDBPyConnection,
                     paths: list[Path]) -> None:
    """Read, standardize and append historical trip files."""
    for path in paths:
        _LOG.info("Processing historical file: %s", path)
        frame = standardize_pre_2020(
            pd.read_csv(path, dtype=str, low_memory=False), str(path)
        )
        frame["rideable_type"] = "classic_bike"
        frame["source_file"] = str(path)
        member_values = frame["member_casual"].astype("string").str.strip().str.lower()
        frame["member_casual"] = member_values.map({
            "subscriber": "member",
            "member": "member",
            "customer": "casual",
            "casual": "casual",
            # Dependent rows are filtered in SQL below, before validation.
            "dependent": "dependent",
        })
        con.register("historical_frame", frame)
        try:
            con.execute(f"""
                INSERT INTO final_harmonized_trips
                SELECT
                    CAST(t.ride_id AS VARCHAR),
                    CAST(t.rideable_type AS VARCHAR),
                    {_TIMESTAMP_SQL.format(column='t.started_at')},
                    {_TIMESTAMP_SQL.format(column='t.ended_at')},
                    t.start_station_name,
                    CAST(t.start_station_id AS VARCHAR),
                    t.end_station_name,
                    CAST(t.end_station_id AS VARCHAR),
                    try_cast(s1.latitude AS DOUBLE),
                    try_cast(s1.longitude AS DOUBLE),
                    try_cast(s2.latitude AS DOUBLE),
                    try_cast(s2.longitude AS DOUBLE),
                    t.member_casual,
                    year({_TIMESTAMP_SQL.format(column='t.started_at')}),
                    t.source_file
                FROM historical_frame t
                LEFT JOIN master_stations s1
                    ON trim(CAST(t.start_station_id AS VARCHAR)) = trim(s1.id)
                LEFT JOIN master_stations s2
                    ON trim(CAST(t.end_station_id AS VARCHAR)) = trim(s2.id)
                WHERE lower(trim(CAST(t.member_casual AS VARCHAR))) <> 'dependent'
                  AND {_TIMESTAMP_SQL.format(column='t.started_at')}
                      < TIMESTAMP '2026-09-01 00:00:00'
            """)
        finally:
            con.unregister("historical_frame")


def _append_post_2020(con: duckdb.DuckDBPyConnection,
                      paths: list[Path]) -> None:
    """Append current-schema files while retaining file provenance."""
    for path in paths:
        _LOG.info("Processing current file: %s", path)
        columns = {str(row[0]).strip().lower()
                   for row in con.execute(
                       "DESCRIBE SELECT * FROM read_csv(?, all_varchar=true)",
                       [str(path)]).fetchall()}
        required = {
            "ride_id", "rideable_type", "started_at", "ended_at",
            "start_station_name", "start_station_id", "end_station_name",
            "end_station_id", "start_lat", "start_lng", "end_lat", "end_lng",
            "member_casual",
        }
        missing = sorted(required - columns)
        if missing:
            raise ValueError(
                f"{path}: missing required columns {missing}; "
                f"found {sorted(columns)}"
            )
        con.execute(f"""
            INSERT INTO final_harmonized_trips
            SELECT
                CAST(ride_id AS VARCHAR),
                CAST(rideable_type AS VARCHAR),
                {_TIMESTAMP_SQL.format(column='started_at')},
                {_TIMESTAMP_SQL.format(column='ended_at')},
                start_station_name,
                CAST(start_station_id AS VARCHAR),
                end_station_name,
                CAST(end_station_id AS VARCHAR),
                try_cast(start_lat AS DOUBLE),
                try_cast(start_lng AS DOUBLE),
                try_cast(end_lat AS DOUBLE),
                try_cast(end_lng AS DOUBLE),
                {_member_case_sql('member_casual')},
                year({_TIMESTAMP_SQL.format(column='started_at')}),
                ? AS source_file
            FROM read_csv(?, union_by_name = true, all_varchar = true)
            WHERE lower(trim(CAST(member_casual AS VARCHAR))) <> 'dependent'
              AND {_TIMESTAMP_SQL.format(column='started_at')}
                  < TIMESTAMP '2026-09-01 00:00:00'
        """, [str(path), str(path)])


def build_dataset(data_dir: str = "data/raw",
                  output_dir: str = "data/processed/trips",
                  database_path: str = "bikeshare_dataset.duckdb",
                  memory_limit: str | None = None,
                  threads: int | None = None) -> dict[str, Any]:
    """Build a year-partitioned Parquet dataset from CSV files.

    The input window is intentionally capped before September 2026. Rows whose
    member type is Dependent are excluded, matching the cleaning step in the
    original notebook. Source ZIPs are not deleted; extract them into DATA_DIR
    before running this function.

    Args:
        data_dir: Folder containing the extracted CSV files.
        output_dir: Destination for the year-partitioned Parquet dataset.
        database_path: DuckDB database file to create.
        memory_limit: Optional DuckDB memory cap such as ``"4GB"``. Leave unset
            to use DuckDB's default (about 80% of RAM); set it lower if other
            programs need memory while the import runs.
        threads: Optional thread count. Fewer threads use less memory.
    """
    root = Path(data_dir)
    if not root.exists():
        raise FileNotFoundError(
            f"Data directory does not exist: {root.resolve()}. "
            "Extract the source ZIP files into this directory first."
        )
    pre_files, post_files, station_files = _discover_csvs(root)
    if not pre_files and not post_files:
        raise ValueError(f"No recognized trip CSV files found under {root}")

    schema = """
        CREATE TABLE final_harmonized_trips (
            ride_id VARCHAR, rideable_type VARCHAR,
            started_at TIMESTAMP, ended_at TIMESTAMP,
            start_station_name VARCHAR, start_station_id VARCHAR,
            end_station_name VARCHAR, end_station_id VARCHAR,
            start_lat DOUBLE, start_lng DOUBLE, end_lat DOUBLE, end_lng DOUBLE,
            member_casual VARCHAR, year INTEGER, source_file VARCHAR
        )
    """
    with duckdb.connect(database_path) as con:
        con.execute("SET preserve_insertion_order = false")
        if memory_limit:
            con.execute("SET memory_limit = ?", [memory_limit])
        if threads:
            con.execute(f"SET threads = {int(threads)}")
        con.execute("DROP TABLE IF EXISTS final_harmonized_trips")
        con.execute(schema)
        _create_station_table(con, station_files)
        _append_pre_2020(con, pre_files)
        _append_post_2020(con, post_files)

        invalid = con.execute("""
            SELECT
                count(*) FILTER (WHERE started_at IS NULL) AS bad_start,
                count(*) FILTER (WHERE ended_at IS NULL) AS bad_end,
                count(*) FILTER (WHERE member_casual NOT IN ('member', 'casual')
                                 OR member_casual IS NULL) AS bad_membership,
                count(*) FILTER (WHERE year IS NULL) AS bad_year
            FROM final_harmonized_trips
        """).fetchone()
        if any(invalid):
            raise ValueError(
                "Validation failed (NULL/unrecognized start/end timestamp, "
                f"membership or year). Counts: {invalid}"
            )

        # Retain one deterministic record per ride ID. Memory-friendly: first
        # find the (normally few) duplicated IDs, then window over only those
        # rows and delete the extras in place. Windowing over the whole table
        # and copying it ran out of memory on the full dataset.
        con.execute("""
            CREATE OR REPLACE TEMP TABLE duplicate_ids AS
            SELECT ride_id
            FROM final_harmonized_trips
            WHERE ride_id IS NOT NULL
            GROUP BY ride_id
            HAVING count(*) > 1
        """)
        con.execute("""
            DELETE FROM final_harmonized_trips
            WHERE rowid IN (
                SELECT rowid
                FROM (
                    SELECT rowid, row_number() OVER (
                        PARTITION BY ride_id
                        ORDER BY source_file, started_at, ended_at
                    ) AS row_num
                    FROM final_harmonized_trips
                    WHERE ride_id IN (SELECT ride_id FROM duplicate_ids)
                )
                WHERE row_num > 1
            )
        """)
        con.execute("DROP TABLE duplicate_ids")

        destination = Path(output_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            import shutil
            shutil.rmtree(destination)
        # DuckDB COPY destinations are SQL identifiers/literals, not query
        # parameters. Escape apostrophes in a user-supplied path explicitly.
        destination_sql = str(destination).replace("'", "''")
        con.execute(f"""
            COPY final_harmonized_trips
            TO '{destination_sql}'
            (FORMAT PARQUET, PARTITION_BY (year), COMPRESSION ZSTD)
        """)

        counts = con.execute("""
            SELECT year, count(*) AS trips
            FROM final_harmonized_trips
            GROUP BY year ORDER BY year
        """).fetchall()
        return {
            "total_trips": sum(count for _, count in counts),
            "counts_by_year": counts,
            "output_dir": str(destination),
            "database_path": database_path,
        }
