"""Download the Divvy trip-data ZIP archives into data/archives on any OS.

This replaces the ``aws s3 sync`` command with plain HTTPS requests, so no AWS
CLI is needed. The bucket is public and read-only.

Already-downloaded archives with a matching size are skipped, so the script is
safe to re-run to resume an interrupted download or to pick up new months.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_BASE_URL = "https://divvy-tripdata.s3.amazonaws.com"
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_RETRIES = 3
_CHUNK = 1024 * 1024


def _open(url: str):
    """Open a URL with a few retries for transient network errors."""
    last_error: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            return urllib.request.urlopen(url, timeout=60)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < _RETRIES:
                time.sleep(2 * attempt)
    raise ConnectionError(f"Could not reach {url}: {last_error}") from last_error


def list_archives(base_url: str) -> list[tuple[str, int]]:
    """Return (key, size_in_bytes) for every .zip object in the bucket."""
    archives: list[tuple[str, int]] = []
    token: str | None = None
    while True:
        query = {"list-type": "2"}
        if token:
            query["continuation-token"] = token
        url = f"{base_url}/?{urllib.parse.urlencode(query)}"
        with _open(url) as response:
            root = ET.fromstring(response.read())
        for item in root.iter(f"{_S3_NS}Contents"):
            key = item.findtext(f"{_S3_NS}Key") or ""
            size = int(item.findtext(f"{_S3_NS}Size") or 0)
            name = Path(key).name
            if key.lower().endswith(".zip") and not name.startswith("._"):
                archives.append((key, size))
        if root.findtext(f"{_S3_NS}IsTruncated") == "true":
            token = root.findtext(f"{_S3_NS}NextContinuationToken")
            if not token:
                break
        else:
            break
    return sorted(archives)


def download_archives(base_url: str, output_dir: Path) -> None:
    """Download every archive that is missing or has the wrong size."""
    output_dir.mkdir(parents=True, exist_ok=True)
    archives = list_archives(base_url)
    if not archives:
        raise FileNotFoundError(f"No ZIP files listed at {base_url}")

    print(f"Found {len(archives)} archives. Saving to {output_dir.resolve()}")
    for index, (key, size) in enumerate(archives, start=1):
        # Use only the file name so a key can never write outside output_dir.
        target = output_dir / Path(key).name
        if target.exists() and target.stat().st_size == size:
            print(f"[{index}/{len(archives)}] {target.name}: already downloaded")
            continue

        print(f"[{index}/{len(archives)}] {target.name}: downloading...")
        partial = target.with_name(target.name + ".part")
        url = f"{base_url}/{urllib.parse.quote(key)}"
        with _open(url) as response, partial.open("wb") as dest:
            while chunk := response.read(_CHUNK):
                dest.write(chunk)
        if partial.stat().st_size != size:
            partial.unlink(missing_ok=True)
            raise IOError(f"{target.name}: size mismatch after download")
        partial.replace(target)

    print("All archives downloaded.")


def main() -> None:
    """Parse arguments and download the archives."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/archives"))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help="S3 bucket URL (override only for testing).")
    args = parser.parse_args()
    try:
        download_archives(args.base_url.rstrip("/"), args.output_dir)
    except (ConnectionError, FileNotFoundError, IOError) as exc:
        sys.exit(f"Error: {exc}")


if __name__ == "__main__":
    main()
