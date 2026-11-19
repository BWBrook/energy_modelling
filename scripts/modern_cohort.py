"""Extract the pre-replay semi-scheduled wind and solar cohort from AEMO's May 2023 snapshot."""

import argparse
import csv
import hashlib
import io
import os
from collections import Counter
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen

from openpyxl import load_workbook


WORKBOOK_URL = (
    "https://www.aemo.com.au/-/media/files/electricity/nem/planning_and_forecasting/"
    "generation_information/2023/nem-generation-information-may-2023.xlsx"
    "?rev=e97a0e72cd5840f98f18a20408a3bfbf&sc_lang=en"
)
WORKBOOK_SHA256 = "6006837560d2e4d654d867a6e20bc9f942a7da8b9db7b7b6bb13795f3334fb4b"
SHEET = "ExistingGeneration&NewDevs"
REGIONS = {"NSW1", "QLD1", "SA1", "TAS1", "VIC1"}


def extract_rows(rows):
    next(rows)  # The May 2023 sheet places its headings in row 2.
    headers = next(rows)
    fields = ("DUID", "Region", "Fuel Bucket Summary", "Unit Status", "Dispatch Type")
    if any(headers.count(field) != 1 for field in fields):
        raise ValueError(f"Missing or ambiguous required headings in {SHEET}")
    indices = [headers.index(field) for field in fields]
    cohort = {}
    missing_duids = 0
    for line, row in enumerate(rows, start=3):
        duid, region, fuel, status, dispatch = (row[i] for i in indices)
        if status != "In Service" or dispatch != "SS" or fuel not in {"Wind", "Solar"}:
            continue
        if duid is None or duid == "":
            missing_duids += 1
            continue
        if not isinstance(duid, str) or not duid.isascii() or not duid.isalnum():
            raise ValueError(f"Ambiguous DUID at {SHEET} row {line}: {duid!r}")
        duid = duid.upper()  # The workbook spells AEMO's KIATAWF1 as KiataWF1.
        if region not in REGIONS:
            raise ValueError(f"Unrecognised region for {duid}: {region!r}")
        entry = (region, fuel.lower())
        if duid in cohort and cohort[duid] != entry:
            raise ValueError(f"Conflicting region or fuel for {duid}: {cohort[duid]} and {entry}")
        cohort[duid] = entry
    return cohort, missing_duids


def save_bytes(path, content):
    """Leave an identical existing file in place and publish new bytes atomically."""
    if path.exists() and path.read_bytes() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent) as tmp:
        tmp.write(content)
        tmp.flush()
        os.link(tmp.name, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path, help="Path to the May 2023 generation information XLSX")
    parser.add_argument("output", type=Path, help="Path for the derived duid,region,profile CSV")
    parser.add_argument("--fetch", action="store_true", help="Download the workbook from AEMO if absent")
    args = parser.parse_args()
    if args.fetch and not args.workbook.exists():
        request = Request(WORKBOOK_URL, headers={
            "User-Agent": "energy-modelling/0.1 (+https://github.com/BWBrook/energy_modelling)"
        })
        with urlopen(request, timeout=60) as response:
            source = response.read()
    else:
        source = args.workbook.read_bytes()
    if hashlib.sha256(source).hexdigest() != WORKBOOK_SHA256:
        raise ValueError("May 2023 generation information workbook SHA256 mismatch")
    if args.fetch:
        save_bytes(args.workbook, source)

    with closing(load_workbook(io.BytesIO(source), read_only=True, data_only=True)) as workbook:
        cohort, missing = extract_rows(iter(workbook[SHEET].values))
    counts = Counter(profile for _, profile in cohort.values())
    if counts != {"wind": 57, "solar": 59} or missing != 6:
        raise ValueError(f"Unexpected May 2023 cohort: {counts}, {missing} unidentifiable rows")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("duid", "region", "profile"))
    writer.writerows((duid, *cohort[duid]) for duid in sorted(cohort))
    save_bytes(args.output, buffer.getvalue().encode("utf-8"))
    print(f"Wrote {len(cohort)} DUIDs ({counts['wind']} wind, {counts['solar']} solar). "
          f"Excluded {missing} in-service semi-scheduled rows without a DUID.")


if __name__ == "__main__":
    main()
