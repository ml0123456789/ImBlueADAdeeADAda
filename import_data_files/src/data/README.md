# Divvy Bike-Share Data: Download, Clean, and Import

This project downloads the public Divvy trip-data archives, extracts them, and
combines the historical (pre-2020) and current (2020 onward) trip files into
one harmonized dataset, stored as:

- a **year-partitioned Parquet dataset** in `data/processed/trips/`, and
- a **DuckDB database**, `bikeshare_dataset.duckdb`, containing the unified table.

It works on **Windows, macOS, and Linux** and needs nothing beyond Python. No
AWS CLI, 7-Zip, or manual file sorting is required.

## The workflow at a glance

```text
download_data.py        prepare_data.py          import_data_fixed.ipynb
(S3 bucket)  ───────►   (extract ZIPs)  ───────►  (clean + harmonize + export)
 data/archives/*.zip     data/raw/**/*.csv         data/processed/trips/year=*/
                                                   bikeshare_dataset.duckdb
```

| Step | Command | Reads | Writes |
|------|---------|-------|--------|
| 1. Download | `python download_data.py` | Divvy S3 bucket | `data/archives/*.zip` |
| 2. Extract | `python prepare_data.py` | `data/archives/` | `data/raw/` |
| 3. Import | run `import_data_fixed.ipynb` | `data/raw/` | `data/processed/trips/`, `bikeshare_dataset.duckdb` |

## Project layout

```text
.
├── pip_requirements.txt
├── download_data.py          # step 1: download ZIPs (pure Python)
├── prepare_data.py           # step 2: extract ZIPs (pure Python)
├── import_data_fixed.ipynb   # step 3: run the pipeline
├── src/data/data.py          # the cleaning/harmonizing pipeline itself
├── src/data/README.md
└── data/                     # created as you go; git-ignored
    ├── archives/             # downloaded ZIPs (kept after extraction)
    ├── raw/                  # extracted CSVs
    └── processed/trips/      # output Parquet, one folder per year
```

All commands below are run **from the project root** (the folder containing
this README). Paths are relative, so the project can live anywhere.

## 0. Prerequisites

- **Python 3.10–3.13.** The pinned dependencies (notably pandas 2.2.3) may not
  have prebuilt packages for newer Python versions.
- **Free disk space.** The archives, the extracted CSVs, and the output Parquet
  are all kept on disk at the same time, and the full history is several
  gigabytes. Check you have room before starting.
- An internet connection for step 1.

## 1. Create a virtual environment and install packages

Do this once.

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r pip_requirements.txt
```

**Windows (PowerShell)**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r pip_requirements.txt
```

If PowerShell refuses to run the activation script, allow it for the current
window only and try again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**Windows (Command Prompt)** — activate with `.venv\Scripts\activate.bat`
instead.

When the environment is active your prompt starts with `(.venv)`. Activate it
again in every new terminal before running any command below.

> **Keep the pinned versions.** `pip_requirements.txt` pins `pandas==2.2.3`
> and `duckdb==1.4.1`. The pipeline hands pandas DataFrames to DuckDB, and
> pandas 3.x will fail with `Data type 'str' not recognized`. If you see that
> error, reinstall from `pip_requirements.txt` inside a fresh virtual
> environment.

## 2. Download the Divvy ZIP files

```bash
python download_data.py
```

This lists the public `divvy-tripdata` S3 bucket and saves every `.zip` into
`data/archives/`. It is safe to re-run: files that are already complete are
skipped, so you can resume an interrupted download or fetch newly published
months later. Partial downloads are written as `*.part` files and only renamed
once the size matches.

<details>
<summary>Alternative: use the AWS CLI instead</summary>

If you prefer the AWS CLI, install it for your OS (Windows:
`winget install Amazon.AWSCLI`; macOS: `brew install awscli`; Linux: your
package manager or the
[official installer](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)),
open a **new** terminal so `aws` is on your `PATH`, then run:

```bash
aws s3 sync s3://divvy-tripdata data/archives --exclude "*" --include "*.zip" --no-sign-request
```

The result is the same: ZIPs in `data/archives/`.

</details>

You can also place ZIP files in `data/archives/` yourself if you obtained them
another way.

## 3. Extract the archives

```bash
python prepare_data.py
```

This uses Python's built-in `zipfile` module to extract every ZIP in
`data/archives/` into `data/raw/`. Compared with the old manual process:

- The **ZIPs are kept**, so you can re-extract at any time.
- macOS/Windows metadata (`__MACOSX/`, `._*` files, `.DS_Store`) is skipped
  automatically; there is no need to delete anything by hand.
- Unsafe paths inside an archive (such as `../../x.csv`) are rejected.

Optional flags if your folders are elsewhere:

```bash
python prepare_data.py --zip-dir path/to/zips --output-dir path/to/raw
```

**You do not need to sort the CSVs into `Pre 2020` / `Post 2020` / `Stations` /
`Trips` folders.** The pipeline recognises each file by its column headers, so
the folder layout under `data/raw/` doesn't matter (nested folders are fine):

| Header contains | Treated as |
|-----------------|------------|
| `ride_id`, `started_at`, `ended_at` | current trip data (including `Divvy_Trips_2020_Q1.csv`) |
| `trip_id` (or the 2018 `01 - Rental Details Rental ID` / `Rental ID` variants) | historical trip data |
| `id`, `latitude`, `longitude` | historical station coordinates |

Any CSV that matches none of these stops the build with an error naming the
file and its columns, rather than being silently ignored.

## 4. Run the import

Start Jupyter from the project root with the virtual environment active:

```bash
jupyter notebook
```

Open `import_data_fixed.ipynb` and run the cells in order. Don't change any
paths: they are relative to the project root.

<details>
<summary>Alternative: run without Jupyter</summary>

```bash
python -c "from src.data.data import build_dataset; print(build_dataset())"
```

This does exactly what the notebook's main cell does and prints the totals.

</details>

I haven't benchmarked the current pipeline on the full dataset. The original
Windows notebook took roughly 5½ minutes, and times depend on your machine and
the amount of data.

### What the pipeline does

1. **Classifies** each CSV as historical trips, current trips, or stations (see
   the table above).
2. **Builds a station lookup** from the historical station files: one
   coordinate record per station ID.
3. **Standardizes the historical trips**: renames the various old headers to the
   current schema (`trip_id` → `ride_id`, `starttime` → `started_at`,
   `usertype` → `member_casual`, and so on), sets `rideable_type` to
   `classic_bike`, and fills start/end coordinates from the station lookup
   (the old files have none).
4. **Standardizes membership labels**: `Subscriber`/`member` → `member`,
   `Customer`/`casual` → `casual`.
5. **Excludes** rows with user type `Dependent`, and any trip that starts on or
   after **2026-09-01**.
6. **Parses timestamps** in both the ISO (`2021-04-01 00:00:00`) and US
   (`3/31/2016 23:30`) formats.
7. **Validates**: the build stops with an error if any timestamp, year, or
   membership value could not be parsed or recognised.
8. **De-duplicates** by `ride_id`, keeping one deterministic row per ID (so a
   ride that appears in two overlapping files is kept once, not dropped).
9. **Exports** the result to Parquet partitioned by `year`, and keeps it as
   the `final_harmonized_trips` table in `bikeshare_dataset.duckdb`.

### Output schema

| Column | Type | Notes |
|--------|------|-------|
| `ride_id` | VARCHAR | |
| `rideable_type` | VARCHAR | `classic_bike` for all pre-2020 rows |
| `started_at`, `ended_at` | TIMESTAMP | |
| `start_station_name`, `start_station_id` | VARCHAR | |
| `end_station_name`, `end_station_id` | VARCHAR | |
| `start_lat`, `start_lng`, `end_lat`, `end_lng` | DOUBLE | Pre-2020: from the station lookup; may be NULL (see limitations) |
| `member_casual` | VARCHAR | `member` or `casual` |
| `source_file` | VARCHAR | CSV the row came from |
| `year` | INTEGER | Year of `started_at`; also the Parquet partition |

The DuckDB file also contains a small `master_stations` table (the station
lookup).

## 5. Query the result

For large data, query with DuckDB instead of loading everything into pandas.

> **Note on the `year` column.** In the Parquet files, `year` is stored in the
> folder name (`year=2021/`), not inside the files. DuckDB restores it with
> `hive_partitioning = true`, and pandas/PyArrow does so automatically when you
> read the whole folder.

### Option A: Query the Parquet dataset with DuckDB

```python
import duckdb

con = duckdb.connect()
trips = "read_parquet('data/processed/trips/**/*.parquet', hive_partitioning = true)"

print(con.sql(f"SELECT * FROM {trips} LIMIT 5").df())

print(con.sql(f"DESCRIBE SELECT * FROM {trips}").df())

print(con.sql(f"""
    SELECT year, member_casual, count(*) AS trips
    FROM {trips}
    GROUP BY ALL ORDER BY ALL
""").df())

con.close()
```

### Option B: Query the DuckDB database directly

```python
import duckdb

con = duckdb.connect("bikeshare_dataset.duckdb", read_only=True)

print(con.sql("SELECT * FROM final_harmonized_trips LIMIT 5").df())
print(con.sql("DESCRIBE final_harmonized_trips").df())

row_count = con.execute("SELECT COUNT(*) FROM final_harmonized_trips").fetchone()[0]
print(f"Total row count: {row_count:,}")

con.close()
```

### Option C: Load into pandas

Filtering by year loads only that year's partition, which keeps memory use low:

```python
import pandas as pd

df_2023 = pd.read_parquet("data/processed/trips", filters=[("year", "=", 2023)])
```

Loading the entire dataset into pandas needs a lot of RAM (the original author
suggested 32 GB or more). Prefer Options A or B unless you have it.

## Re-running and updating

- **New months published?** Run `python download_data.py` again (only new
  files are fetched), then `python prepare_data.py`, then re-run the notebook.
- The import **rebuilds everything from scratch**: it recreates the DuckDB
  table and deletes and rewrites `data/processed/trips/`. It's safe to re-run,
  but don't keep hand-made files in that folder.
- `prepare_data.py` overwrites existing files in `data/raw/` with the ZIP
  contents.
- If a DuckDB connection (another notebook, a Python shell) is still holding
  `bikeshare_dataset.duckdb` open, close it before re-running the import.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `python: command not found` (macOS/Linux) | Use `python3` to create the venv; after activating it, `python` works. |
| `No module named duckdb` (or pandas) | The virtual environment isn't active, or Jupyter was started outside it. Activate `.venv`, then run `jupyter notebook`. |
| `No module named 'src'` in the notebook | Jupyter wasn't started from the project root. Close it and restart from there. |
| `Data type 'str' not recognized` | pandas 3.x is installed. Reinstall from `pip_requirements.txt` in a fresh venv. |
| `No ZIP files found in data/archives` | Run step 2, or put your ZIPs in that folder. |
| `Unrecognized CSV header in ...` | An unexpected CSV is in `data/raw/`. Inspect it, and remove it if it isn't trip or station data. |
| `Validation failed (...) Counts: (a, b, c, d)` | Rows with unparseable start time, end time, membership label, or year. The counts are in that order; find the offending file in the log output. |
| Download stops partway | Re-run `python download_data.py`; it resumes by skipping completed files. |

## Known limitations

- **Station-coordinate backfill is not finished.** Historical station IDs that
  are missing from the historical station files get NULL coordinates; they are
  not yet backfilled from 2020 trip coordinates. The last cell of the notebook
  reports NULL coordinates per year. Decide how your project handles this
  before treating pre-2020 coordinates as final.
- The import window ends before 2026-09-01 (a constant in `src/data/data.py`;
  change it there to include later data).
- `Dependent` user-type rows are excluded.
- Only CSV files are read. Non-CSV files in the archives (for example older
  Excel station files) are extracted but ignored.

## Version control

Don't commit data. The included `.gitignore` already excludes `data/archives/`,
`data/raw/`, `data/processed/`, `*.duckdb`, `*.parquet`, and `.venv/`.
