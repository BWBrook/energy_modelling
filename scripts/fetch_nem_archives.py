"""Fetch or check the AEMO source files pinned for the 2023–26 replay."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from functools import partial
import hashlib
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen


MANIFEST = Path(__file__).resolve().parents[1] / "data/nem_replay_sources.csv"


def verify(path, record):
    if path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"Unexpected size for {path}")
    with path.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != record["sha256"]:
            raise ValueError(f"SHA256 mismatch for {path}")


def fetch(root, check_only, record):
    path = root / record["path"]
    if path.exists() or check_only:
        verify(path, record)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(record["url"], headers={"User-Agent": "energy-modelling/0.1 (+https://github.com/BWBrook/energy_modelling)"})
    with NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        part = Path(tmp.name)
    try:
        with urlopen(request, timeout=180) as stream, part.open("wb") as out:
            shutil.copyfileobj(stream, out)
        verify(part, record)
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--check-only", action="store_true", help="Verify local files without downloading")
    args = parser.parse_args()
    with MANIFEST.open(newline="") as f:
        records = list(csv.DictReader(f))
    with ThreadPoolExecutor(3) as pool:
        list(pool.map(partial(fetch, args.directory, args.check_only), records))
    print(f"Verified {len(records)} AEMO source files.")
