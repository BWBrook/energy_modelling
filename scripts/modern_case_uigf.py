"""Recover missing five-minute UIGFs from AEMO's original NEMDE dispatch cases."""

import argparse
import csv
import hashlib
import math
import shutil
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import urlopen
from zipfile import ZipFile


AEST = timezone(timedelta(hours=10))
STEP = timedelta(minutes=5)
ROOT = "https://www.nemweb.com.au/Data_Archive/Wholesale_Electricity/NEMDE"
SOURCE_HASHES = {
    "20230701": "37f4dbab4d6ae4df7cef6f6632c44873f29024455c3c9818120303fef5b79d41",
    "20230807": "5f3f7c621e9f3de3ebf89f62dfaa0badae1e8d86f88f608495ded7cfa71ac33d",
    "20231205": "90e30f1db896c6e063997eaedcdeef0163701aa7fedac8f3a90a951082616b9e",
    "20250930": "52a3fe9eff49ab097758915f5d1b2424dd2c196265ad42465a22a7c6968e7140",
}


def starts():
    def local(value):
        return datetime.fromisoformat(value).replace(tzinfo=AEST)

    controls = ["2023-07-01T12:00", "2023-08-07T13:25", "2023-08-07T13:30",
                "2023-08-07T13:35", "2023-08-07T13:40", "2023-12-05T13:35",
                "2023-12-05T13:50", "2025-10-01T00:00", "2025-10-01T00:05"]
    requests = {local(t): "control" for t in controls}
    for t in ["2023-12-05T13:40", "2023-12-05T13:45"]:
        requests[local(t)] = "patch"
    first = local("2025-09-30T04:00")
    for i in range(240):
        requests[first + i * STEP] = "patch"
    return requests


def write_csv(path, header, rows):
    with path.open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def get_archive(raw, day):
    name = f"NemSpdOutputs_{day}_loaded.zip"
    path = raw / name
    url = f"{ROOT}/{day[:4]}/NEMDE_{day[:4]}_{day[4:6]}/NEMDE_Market_Data/NEMDE_Files/{name}"
    if not path.is_file():
        with NamedTemporaryFile(dir=raw, delete=False) as tmp:
            part = Path(tmp.name)
        try:
            with urlopen(url, timeout=150) as source, part.open("wb") as dest:
                shutil.copyfileobj(source, dest)
            with part.open("rb") as f:
                if hashlib.file_digest(f, "sha256").hexdigest() != SOURCE_HASHES[day]:
                    raise ValueError(f"Unexpected source hash: {url}")
            part.replace(path)
        finally:
            part.unlink(missing_ok=True)
    with path.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    if digest != SOURCE_HASHES[day]:
        raise ValueError(f"Unexpected source hash: {path}")
    return path, (name, url, path.stat().st_size, digest)


def extract(xml, case_id, end, cohort):
    root = ET.fromstring(xml)
    case = root.find("NemSpdInputs/Case")
    if case is None or (case.get("CaseID"), case.get("CaseType"), case.get("Intervention")) != (
        case_id, "DS", "False"
    ):
        raise ValueError(f"Unexpected dispatch case: {case_id}")
    periods = root.findall("NemSpdInputs/PeriodCollection/Period")
    solved = root.findall("NemSpdOutputs/PeriodSolution")
    if len(periods) != 1 or not solved or any(
        node.get("PeriodID") != end.isoformat() for node in [*periods, *solved]
    ):
        raise ValueError(f"Case {case_id} does not match endpoint {end}")
    values = {}
    for trader in periods[0].findall("TraderPeriodCollection/TraderPeriod"):
        duid = trader.attrib["TraderID"].upper()
        value = trader.get("UIGF")
        if duid not in cohort or value is None:
            continue
        if (duid in values or trader.get("RegionID") != cohort[duid]
                or not math.isfinite(float(value)) or float(value) < 0):
            raise ValueError(f"Invalid or duplicate forecast: {case_id} {duid}")
        values[duid] = value
    if not values:
        raise ValueError(f"Case {case_id} contains no forecasts for cohort")
    return values


def run(cohort_path, out):
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    with cohort_path.open(newline="") as f:
        cohort = {row["duid"]: row["region"] for row in csv.DictReader(f)}
    requests = defaultdict(list)
    for start, purpose in sorted(starts().items()):
        day = start.replace(hour=4, minute=0)
        if start < day:
            day -= timedelta(days=1)
        sequence = (start - day) // STEP + 1
        requests[day.strftime("%Y%m%d")].append((start, sequence, purpose))
    sources, cases = [], []
    values = {"patch": [], "control": []}
    for day, group in requests.items():
        path, provenance = get_archive(raw, day)
        sources.append(provenance)
        with ZipFile(path) as archive:
            names = archive.namelist()
            for start, sequence, purpose in group:
                case_id = f"{day}{sequence:03}"
                end = start + STEP
                prefix = f"NEMSPDOutputs_{case_id}"
                members = [name for name in names if name.startswith(prefix)]
                if not members:
                    if case_id not in {"20231205117", "20231205118"}:
                        raise ValueError(f"Missing dispatch case {case_id}")
                    cases.append((start.isoformat(), end.isoformat(), case_id, purpose,
                                  "absent from source ZIP", path.name, "", "", 0, ""))
                    continue
                if members != [f"{prefix}00.loaded"]:
                    raise ValueError(f"Unexpected case versions for {case_id}: {members}")
                xml = archive.read(members[0])
                forecasts = extract(xml, case_id, end, cohort)
                digest = hashlib.sha256(xml).hexdigest()
                missing = sorted(cohort.keys() - forecasts.keys())
                cases.append((start.isoformat(), end.isoformat(), case_id, purpose, "present",
                              path.name, members[0], digest, len(forecasts), " ".join(missing)))
                values[purpose].extend((start.isoformat(), duid, value)
                                       for duid, value in sorted(forecasts.items()))
    write_csv(out / "archives.csv", ["file", "url", "bytes", "sha256"], sources)
    write_csv(out / "cases.csv", ["timestamp_start", "timestamp_end", "case_id", "purpose",
                                 "status", "archive", "member", "member_sha256",
                                 "observed_cohort_duids", "unreported_duids"], cases)
    for purpose, filename in [("patch", "patches.csv"), ("control", "controls.csv")]:
        write_csv(out / filename, ["timestamp_start", "duid", "uigf_mw"], values[purpose])


def compare_controls(archives, out):
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.csv as acsv

    from modern_resources import trailer

    forecasts = defaultdict(dict)
    with (out / "controls.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            end = datetime.fromisoformat(row["timestamp_start"]) + STEP
            forecasts[end][row["duid"]] = float(row["uigf_mw"])
    months = defaultdict(list)
    for end in forecasts:
        months[end.strftime("%Y%m")].append(end)
    cols = {"SETTLEMENTDATE": pa.string(), "DUID": pa.string(), "RUNNO": pa.int8(),
            "INTERVENTION": pa.int8(), "AVAILABILITY": pa.float64(), "UIGF": pa.float64()}
    checks = []
    for month, times in months.items():
        path = archives / f"DISPATCHLOAD_{month}.zip"
        labels = {end.strftime("%Y/%m/%d %H:%M:%S"): end for end in times}
        wanted = pa.array(list(labels))
        mms = {}
        with ZipFile(path) as archive, archive.open(archive.namelist()[0]) as f:
            f.readline()
            reader = acsv.open_csv(f, read_options=acsv.ReadOptions(block_size=2**23),
                                   parse_options=acsv.ParseOptions(invalid_row_handler=trailer),
                                   convert_options=acsv.ConvertOptions(column_types=cols,
                                                                      include_columns=list(cols)))
            for batch in reader:
                keep = pc.and_(pc.is_in(batch["SETTLEMENTDATE"], value_set=wanted),
                               pc.equal(batch["RUNNO"], 1))
                for row in batch.filter(keep).to_pylist():
                    end = labels[row["SETTLEMENTDATE"]]
                    key = end, row["DUID"].upper(), row["INTERVENTION"]
                    if key[1] in forecasts[end]:
                        if key in mms or key[2] not in (0, 1):
                            raise ValueError(f"Unexpected MMS dispatch run: {key}")
                        mms[key] = row
        for end in times:
            reference = "AVAILABILITY" if end <= datetime(2023, 8, 7, 13, 35, tzinfo=AEST) else "UIGF"
            for field in ("AVAILABILITY", "UIGF"):
                errors = []
                for duid, value in forecasts[end].items():
                    row = mms.get((end, duid, 1), mms.get((end, duid, 0)))
                    if row and row[field] is not None:
                        errors.append(abs(value - row[field]))
                mismatched = sum(error > 1e-5 for error in errors)
                checks.append(((end - STEP).isoformat(), end.isoformat(), path.name, field,
                               len(forecasts[end]), len(errors), mismatched, max(errors, default=None),
                               field == reference))
    write_csv(out / "checks.csv", ["timestamp_start", "timestamp_end", "mms_archive", "mms_field",
                                  "case_duids", "matched_nonnull_duids", "differ_over_1e-5_mw",
                                  "max_abs_error_mw", "expected_uigf_field"], checks)
    if any(ref and (n != matched or diff) for _, _, _, _, n, matched, diff, _, ref in checks):
        raise ValueError(f"Original case and expected MMS field disagree. See {out / 'checks.csv'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cohort", type=Path, help="Private fixed DUID/region lookup")
    parser.add_argument("output", type=Path, help="Private results and raw archive cache")
    parser.add_argument("--dispatch-archives", type=Path, help="Cross-check sampled cases against MMS")
    args = parser.parse_args()
    run(args.cohort, args.output)
    if args.dispatch_archives:
        compare_controls(args.dispatch_archives, args.output)
