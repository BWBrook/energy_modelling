"""Aggregate AEMO regional grid demand and rooftop PV to whole-NEM hour starts."""

import argparse
import csv
from datetime import datetime, timedelta, timezone
from io import TextIOWrapper
from pathlib import Path
from zipfile import ZipFile

import numpy as np


NEM_TIME = timezone(timedelta(hours=10))
START = datetime(2023, 7, 1, tzinfo=NEM_TIME)
MEASURED_START = datetime(2024, 8, 1, tzinfo=NEM_TIME)
END = datetime(2026, 7, 1, tzinfo=NEM_TIME)
REGIONS = ("NSW1", "QLD1", "SA1", "TAS1", "VIC1")
TABLES = {
    "DISPATCHREGIONSUM": (("DISPATCH", "REGIONSUM"), "SETTLEMENTDATE", 5,
                          ("TOTALDEMAND", "DEMAND_AND_NONSCHEDGEN")),
    "DEMANDOPERATIONALACTUAL": (("OPERATIONAL_DEMAND", "ACTUAL"), "INTERVAL_DATETIME", 30,
                                ("OPERATIONAL_DEMAND",)),
    "ROOFTOP_PV_ACTUAL": (("ROOFTOP", "ACTUAL"), "INTERVAL_DATETIME", 30, ("POWER",)),
}


def hourly_table(archive_dir, table, start, end):
    """Yield hour start, NEM MW tuple, satellite substitution count and missing rooftop count."""
    dataset, time_field, minutes, fields = TABLES[table]
    if any(t.utcoffset() != timedelta(hours=10) for t in (start, end)):
        raise ValueError("Use NEM market time (fixed UTC+10) for start and end")
    if start >= end or any((t.minute, t.second, t.microsecond) != (0, 0, 0) for t in (start, end)):
        raise ValueError("Expected a nonempty range of whole hours")
    left, end = start.astimezone(NEM_TIME), end.astimezone(NEM_TIME)
    index_region = {name: i for i, name in enumerate(REGIONS)}
    step = timedelta(minutes=minutes)
    while left < end:
        next_month = (left.replace(day=28, hour=0) + timedelta(days=4)).replace(day=1)
        right = min(next_month, end)
        n = (right - left) // step
        fmt = "%Y/%m/%d %H:%M:%S"
        first, last = left.strftime(fmt), right.strftime(fmt)
        index_time = {(left + (i + 1) * step).strftime(fmt): i for i in range(n)}
        path = archive_dir / f"{table}_{left:%Y%m}.zip"
        values = np.full((2, n, len(REGIONS), len(fields)), np.nan)
        seen = np.zeros(values.shape[:3], dtype=bool)
        with ZipFile(path) as archive:
            files = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(files) != 1:
                raise ValueError(f"{path}: expected one MMS CSV")
            with archive.open(files[0]) as file:
                columns = {}
                for row in csv.reader(TextIOWrapper(file, encoding="utf-8-sig", newline="")):
                    if tuple(row[1:3]) != dataset:
                        continue
                    if row[0] == "I":
                        columns = {name: i for i, name in enumerate(row[4:], 4)}
                        continue
                    if row[0] != "D":
                        continue
                    stamp = row[columns[time_field]]
                    region = row[columns["REGIONID"]]
                    if not first < stamp <= last or region not in index_region:
                        continue
                    if stamp not in index_time:
                        raise ValueError(f"{path}: off-grid timestamp {stamp}")

                    source = 1
                    if table == "DISPATCHREGIONSUM":
                        # INTERVENTION=1 denotes physical dispatch when a pricing run also exists.
                        flag = row[columns["INTERVENTION"]]
                        if row[columns["RUNNO"]] != "1" or flag not in ("0", "1"):
                            raise ValueError(f"{path}: unexpected dispatch run at {stamp}")
                        source = int(flag)
                    elif table == "ROOFTOP_PV_ACTUAL":
                        method = row[columns["TYPE"]]
                        if method not in ("MEASUREMENT", "SATELLITE"):
                            raise ValueError(f"{path}: unexpected rooftop estimate {method!r}")
                        source = int(method == "MEASUREMENT")

                    key = (source, index_time[stamp], index_region[region])
                    if seen[key]:
                        raise ValueError(f"{path}: duplicate {region}, {stamp}, source {source}")
                    seen[key] = True
                    for i, field in enumerate(fields):
                        raw = row[columns[field]]
                        if table == "ROOFTOP_PV_ACTUAL" and raw == "":
                            continue
                        value = float(raw) if raw else np.nan
                        if not np.isfinite(value):
                            raise ValueError(f"{path}: invalid {field} for {region} ending {stamp}")
                        values[(*key, i)] = value

        if table == "DISPATCHREGIONSUM":
            physical = seen[1].any(axis=1)
            if np.any(physical[:, None] & ~seen[1]):
                raise ValueError(f"{path}: missing region in physical intervention run")
        preferred = np.isfinite(values[1, :, :, 0])
        alternate = ~preferred & np.isfinite(values[0, :, :, 0])
        selected = np.where(preferred[:, :, None], values[1], values[0])
        missing = np.isnan(selected[:, :, 0])
        if table != "ROOFTOP_PV_ACTUAL" and missing.any():
            i, j = np.argwhere(missing)[0]
            stamp = left + (int(i) + 1) * step
            raise ValueError(f"{path}: missing {fields[0]} for {REGIONS[j]} ending {stamp}")

        per_hour = 60 // minutes
        mw = selected.sum(axis=1).reshape(-1, per_hour, len(fields)).mean(axis=1)
        satellite = (alternate.reshape(-1, per_hour, len(REGIONS)).sum(axis=(1, 2))
                     if table == "ROOFTOP_PV_ACTUAL" else np.zeros(len(mw), dtype=int))
        absent = missing.reshape(-1, per_hour, len(REGIONS)).sum(axis=(1, 2))
        for i, row in enumerate(mw):
            hourly = tuple(None if np.isnan(v) else float(v) for v in row)
            yield left + timedelta(hours=i), hourly, int(satellite[i]), int(absent[i])
        left = right


def write_demand(archive_dir, output):
    measured = {t: mw[0] for t, mw, _, _ in
                hourly_table(archive_dir, "DEMANDOPERATIONALACTUAL", MEASURED_START, END)}
    dispatch = hourly_table(archive_dir, "DISPATCHREGIONSUM", START, END)
    rooftop = hourly_table(archive_dir, "ROOFTOP_PV_ACTUAL", START, END)
    output.parent.mkdir(parents=True, exist_ok=True)
    part = output.with_suffix(".part")
    try:
        with part.open("w", newline="") as file:
            writer = csv.writer(file, lineterminator="\n")
            writer.writerow(("timestamp", "totaldemand_mw", "demand_and_nonschedgen_mw", "measured_mw",
                             "rooftop_mw", "rooftop_satellite_region_halfhours", "rooftop_missing_region_halfhours"))
            for (t, grid, _, _), (r, pv, satellite, missing) in zip(dispatch, rooftop, strict=True):
                if t != r:
                    raise ValueError(f"Demand and rooftop timestamps differ: {t}, {r}")
                writer.writerow((t.isoformat(), *grid, measured[t] if t >= MEASURED_START else None,
                                 pv[0], satellite, missing))
        part.replace(output)
    finally:
        part.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    write_demand(args.archive_dir, args.output)
