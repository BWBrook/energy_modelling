"""Build fixed-footprint hourly wind and solar traces from AEMO's five-minute UIGFs."""

import argparse
import calendar
from concurrent.futures import ProcessPoolExecutor
import csv
from datetime import datetime, timedelta
from functools import partial
from io import TextIOWrapper
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as acsv


START = np.datetime64("2023-07-01T00:00:00", "s")
STOP = np.datetime64("2026-07-01T00:00:00", "s")
N_STEPS = int((STOP - START) / np.timedelta64(300, "s"))


def stable_ratings(path, candidates):
    """Use the latest version at each effective date, then check the whole study window."""
    history = {d: {} for d in candidates}
    with ZipFile(path) as z, z.open(z.namelist()[0]) as f:
        rows = csv.reader(TextIOWrapper(f))
        header = next(row for row in rows if row[0] == "I")
        for row in rows:
            if row[0] != "D":
                continue
            data = dict(zip(header, row, strict=True))
            duid = data["DUID"].upper()
            if duid not in history:
                continue
            date = data["EFFECTIVEDATE"]
            record = (int(data["VERSIONNO"]), float(data["REGISTEREDCAPACITY"] or 0))
            if date not in history[duid] or history[duid][date][0] < record[0]:
                history[duid][date] = record
    for duid, records in history.items():
        dates = sorted(d for d in records if d < "2026/07/01 00:00:00")
        prior = [d for d in dates if d <= "2023/07/01 00:00:00"]
        if not prior:
            yield duid, None, "no starting rating"
            continue
        ratings = {records[d][1] for d in dates if d >= prior[-1]}
        rating = records[prior[-1]][1]
        reason = "rating changed" if len(ratings) != 1 else ("zero rating" if rating <= 0 else "")
        yield duid, rating, reason


def trailer(row):
    fields = next(csv.reader([row.text]))
    return "skip" if len(fields) == 3 and fields[:2] == ["C", "END OF REPORT"] else "error"


def read_month(path, duids):
    month = datetime.strptime(path.stem.split("_")[-1], "%Y%m")
    # The old MMSDM file boundary can differ from midnight. Use timestamps in adjacent archives.
    origin = np.datetime64(month - timedelta(days=2), "s").astype(int)
    days = calendar.monthrange(month.year, month.month)[1]
    matrix = np.full(((days + 4) * 288, len(duids)), np.nan)
    flags = np.zeros(matrix.shape, dtype=np.uint8)
    types = {"DUID": pa.string(), "SETTLEMENTDATE": pa.timestamp("s"), "UIGF": pa.float64(),
             "AVAILABILITY": pa.float64(),
             "RUNNO": pa.int8(), "INTERVENTION": pa.int8()}
    subset = pa.array(duids)
    with ZipFile(path) as z, z.open(z.namelist()[0]) as f:
        f.readline()
        reader = acsv.open_csv(f, read_options=acsv.ReadOptions(block_size=2**23),
                               parse_options=acsv.ParseOptions(invalid_row_handler=trailer),
                               convert_options=acsv.ConvertOptions(
                                   include_columns=list(types), column_types=types,
                                   timestamp_parsers=["%Y/%m/%d %H:%M:%S"]))
        for batch in reader:
            col = pc.index_in(pc.utf8_upper(batch["DUID"]), value_set=subset)
            # Before bid Max Avail was enabled, semi-scheduled AVAILABILITY reported the UIGF.
            before_change = pc.less_equal(batch["SETTLEMENTDATE"], datetime(2023, 8, 7, 13, 35))
            output = pc.if_else(before_change, pc.coalesce(batch["UIGF"], batch["AVAILABILITY"]),
                                batch["UIGF"])
            selected = (pc.is_valid(col).to_numpy(zero_copy_only=False)
                        & (batch["RUNNO"].to_numpy() == 1))
            if not selected.any():
                continue
            j = col.filter(selected).to_numpy()
            end = batch["SETTLEMENTDATE"].filter(selected).cast(pa.int64()).to_numpy()
            if np.any((end - origin) % 300):
                raise ValueError(f"Timestamp off five-minute grid in {path}")
            i = (end - origin) // 300 - 1
            if i.min() < 0 or i.max() >= len(matrix):
                raise ValueError(f"Timestamp outside monthly archive window in {path}")
            value = output.filter(selected).to_numpy(zero_copy_only=False)
            if np.isinf(value).any() or np.any(value < 0):
                raise ValueError(f"Invalid UIGF in {path}")
            interventions = batch["INTERVENTION"].filter(selected).to_numpy()
            if not np.isin(interventions, [0, 1]).all():
                raise ValueError(f"Unknown intervention flag in {path}")
            for flag in np.unique(interventions):
                which = interventions == flag
                t, unit, v = i[which], j[which], value[which]
                keys = t * len(duids) + unit
                bit = 1 << int(flag)
                if len(np.unique(keys)) != len(t) or np.any(flags[t, unit] & bit):
                    raise ValueError(f"Duplicate interval, run and DUID in {path}")
                # Use the physical intervention run wherever AEMO also published a pricing run.
                take = (flags[t, unit] & 2) == 0
                matrix[t[take], unit[take]] = v[take]
                flags[t, unit] |= bit
    physical = ((flags & 2) != 0).any(axis=1)
    if np.any(flags[physical] == 1):
        raise ValueError(f"Missing physical run for a DUID with a pricing run in {path}")
    offset = int((origin - START.astype(int)) // 300)
    begin, end = max(0, offset), min(N_STEPS, offset + len(matrix))
    return begin, matrix[begin - offset:end - offset]


def run(archives, cohort, patches, out, workers):
    if out.exists():
        raise FileExistsError(out)
    with cohort.open(newline="") as f:
        candidates = {r["duid"]: r for r in csv.DictReader(f)}
    ratings = list(stable_ratings(archives / "DUDETAIL_202606.zip", candidates))
    accepted = [(d, mw) for d, mw, reason in ratings if not reason]
    duids = [d for d, _ in accepted]
    grid = np.full((N_STEPS, len(duids)), np.nan)
    files = [archives / f"DISPATCHLOAD_{y}{m:02}.zip"
             for y in range(2023, 2027) for m in range(1, 13)
             if "202307" <= f"{y}{m:02}" <= "202606"]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for begin, block in pool.map(partial(read_month, duids=duids), files):
            dest = grid[begin:begin+len(block)]
            mask = np.isfinite(block)
            overlap = mask & np.isfinite(dest)
            if not np.array_equal(dest[overlap], block[overlap]):
                raise ValueError("Conflicting data in overlapping monthly archives")
            np.copyto(dest, block, where=mask)
    indices = {duid: j for j, duid in enumerate(duids)}
    base_time = datetime.fromisoformat("2023-07-01T00:00:00+10:00")
    with patches.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["duid"] not in indices:
                continue
            t = datetime.fromisoformat(row["timestamp_start"])
            seconds = (t - base_time).total_seconds()
            if seconds % 300 or not 0 <= seconds < N_STEPS * 300:
                raise ValueError(f"Invalid dispatch case timestamp {t}")
            i, j = int(seconds // 300), indices[row["duid"]]
            value = float(row["uigf_mw"])
            if np.isfinite(grid[i, j]) or not np.isfinite(value) or value < 0:
                raise ValueError(f"Unexpected dispatch case substitution at {t} for {row['duid']}")
            grid[i, j] = value
    count = dict(zip(duids, np.isfinite(grid).sum(axis=0), strict=True))
    # Neither the monthly files nor the original dispatch cases contain these two intervals.
    missing = np.flatnonzero(np.isnan(grid).all(axis=1))
    times = START + missing * np.timedelta64(300, "s")
    if not set(times).issubset({np.datetime64("2023-12-05T13:40:00", "s"),
                                np.datetime64("2023-12-05T13:45:00", "s")}):
        raise ValueError(f"Unexpected fleet-wide missing intervals: {times}")
    full = np.array([count[d] == N_STEPS - len(missing) for d in duids])
    profile = {}
    for tech in ("wind", "solar"):
        select = full & np.array([candidates[d]["profile"] == tech for d in duids])
        if not select.any():
            raise ValueError(f"No complete {tech} series")
        capacity = sum(mw for (d, mw), use in zip(accepted, select, strict=True) if use)
        five_min = grid[:, select].sum(axis=1) / capacity
        five_min[missing] = 0
        if five_min.min() < 0 or five_min.max() > 1:
            raise ValueError(f"{tech} aggregate fraction outside [0,1]")
        profile[tech] = five_min.reshape(-1, 12).mean(axis=1)
    out.mkdir(parents=True, exist_ok=False)
    with (out / "resource_cohort.csv").open("x", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["duid", "region", "profile", "start_registered_mw", "valid_five_min",
                         "expected_five_min", "selection"])
        for d, mw, reason in ratings:
            n = count.get(d)
            writer.writerow([d, candidates[d]["region"], candidates[d]["profile"], mw, n, N_STEPS,
                             reason or ("included" if n == N_STEPS - len(missing) else "incomplete UIGF")])
    with (out / "resource_hours.csv").open("x", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["timestamp", "wind", "solar", "missing_five_min"])
        missing_count = np.bincount(missing // 12, minlength=N_STEPS // 12)
        for i, (wind, solar) in enumerate(zip(profile["wind"], profile["solar"], strict=True)):
            start = START + np.timedelta64(i, "h")
            writer.writerow([str(start) + "+10:00", wind, solar, missing_count[i]])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", type=Path)
    parser.add_argument("cohort", type=Path)
    parser.add_argument("patches", type=Path, help="Timestamped UIGFs from missing dispatch cases")
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    run(args.archives, args.cohort, args.patches, args.output, args.workers)
