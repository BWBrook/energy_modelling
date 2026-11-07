#!/usr/bin/env python3
"""Verify the recovered CSV manifest and regenerate the human-readable catalogue."""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifest.csv"
CATALOGUE = ROOT / "data" / "catalogue.csv"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def notes(filename: str, category: str) -> tuple[str, str, str]:
    if category == "technology":
        return "generator parameter table", "Recovered 2017 model input", "Seven variants; blank first header in some originals is retained in raw file"
    if filename == "nem_trace2.csv":
        return "hourly demand and weather trace", "Recovered 2017 model input", "Eight 8760-hour weather years; demand repeats across years; leap days removed"
    if filename == "nem_trace.csv":
        return "alternative hourly demand and weather trace", "Recovered 2017 preparation material", "Different demand from selected nem_trace2.csv"
    if category == "traces":
        return "hourly trace", "Recovered 2017 preparation material", "Not read by the v0.7 model"
    if filename == "net_load_2026.csv":
        return "derived net-load experiment", "Recovered 2017 preparation material", "Trailing 48 rows labelled 2021 with missing values"
    if filename.startswith("net_load_"):
        return "derived net-load experiment", "Recovered 2017 preparation material", "Not read by the v0.7 model"
    if filename.startswith("Scen2"):
        return "projected demand table", "Recovered 2017 preparation material", "Demand source relationship to nem_trace2 is unresolved"
    if filename == "may_trace.csv":
        return "monthly trace sample", "Recovered 2017 preparation material", "744 rows without calendar dates"
    return "ancillary preparation or scenario table", "Recovered 2017 preparation material", "Schema and provenance require review before reuse"


def main() -> None:
    with MANIFEST.open(newline="") as stream:
        manifest = list(csv.DictReader(stream))
    if not manifest:
        raise SystemExit("manifest is empty")
    output = []
    for row in manifest:
        path = ROOT / row["path"]
        if not path.is_file():
            raise SystemExit(f"missing manifest path: {path}")
        if digest(path) != row["sha256"]:
            raise SystemExit(f"hash mismatch: {path}")
        role, provenance, quality = notes(row["original_filename"], row["category"])
        output.append({**row, "role": role, "provenance": provenance, "quality_notes": quality})
    fields = list(output[0])
    with CATALOGUE.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output)
    print(f"Verified {len(output)} manifest entries and wrote {CATALOGUE}")


if __name__ == "__main__":
    main()
