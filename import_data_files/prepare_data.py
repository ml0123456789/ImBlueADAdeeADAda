"""Extract bike-share source ZIP files into data/raw on any OS."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZipFile


def extract_archives(zip_dir: Path, output_dir: Path) -> None:
    """Extract ZIP archives while skipping macOS metadata files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    archives = sorted(zip_dir.glob("*.zip"))
    if not archives:
        raise FileNotFoundError(f"No ZIP files found in {zip_dir.resolve()}")

    for archive in archives:
        print(f"Extracting {archive.name}...")
        with ZipFile(archive) as zipped:
            for member in zipped.infolist():
                member_path = Path(member.filename)
                parts = member_path.parts
                if (
                    not member.filename
                    or member.is_dir()
                    or "__MACOSX" in parts
                    or any(part.startswith("._") for part in parts)
                    or member_path.name == ".DS_Store"
                ):
                    continue

                # Prevent ZIP path traversal (e.g. ../../outside.csv).
                target = (output_dir / Path(*parts)).resolve()
                root = output_dir.resolve()
                if target != root and root not in target.parents:
                    raise ValueError(
                        f"Unsafe path in {archive.name}: {member.filename}"
                    )

                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as source, target.open("wb") as dest:
                    dest.write(source.read())


def main() -> None:
    """Parse paths and extract all ZIP archives."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip-dir", type=Path, default=Path("data/archives"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    extract_archives(args.zip_dir, args.output_dir)


if __name__ == "__main__":
    main()
