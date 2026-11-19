"""Replay two frozen 2017 fleets against timestamp-matched modern market inputs."""

import argparse
import csv
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import platform

import numpy as np

from energymod.data import read_technologies, read_trace
from weather_replay import SHORTFALL_TOLERANCE_MW, replay


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL = ROOT / "results/weather_test_2017"
AEST = timezone(timedelta(hours=10))
START = datetime(2023, 7, 1, tzinfo=AEST)
STOP = datetime(2026, 7, 1, tzinfo=AEST)
MEASURED_START = datetime(2024, 8, 1, tzinfo=AEST)
LAST_YEAR = datetime(2025, 7, 1, tzinfo=AEST)
TECHS = ROOT / "config/technologies_2017.csv"


def dated_rows(path):
    with path.open(newline="") as f:
        result = {}
        for row in csv.DictReader(f):
            stamp = datetime.fromisoformat(row["timestamp"])
            if stamp.utcoffset() != timedelta(hours=10) or stamp in result:
                raise ValueError(f"Ambiguous timestamp in {path}: {stamp}")
            result[stamp] = row
    return result


def canonical_inputs(demand_file, resources_file, folder):
    demand = dated_rows(demand_file)
    resources = dated_rows(resources_file)
    hours = [START + timedelta(hours=i) for i in range((STOP - START) // timedelta(hours=1))]
    if set(demand) != set(hours) or set(resources) != set(hours):
        raise ValueError("Resource and demand timestamps must each cover the exact three financial years")
    folder.mkdir(parents=True, exist_ok=False)
    missing = {t.isoformat(): int(resources[t]["missing_five_min"]) for t in hours}
    if any(n < 0 or n > 12 for n in missing.values()):
        raise ValueError("Invalid count of missing five-minute observations")
    for basis in ("dispatch", "measured", "underlying"):
        with (folder / f"{basis}.csv").open("x", newline="") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(["timestamp", "period", "duration_hours", "demand_mw", "wind", "solar"])
            for stamp in hours:
                resource = resources[stamp]
                d = demand[stamp]
                if basis == "dispatch":
                    load = float(d["totaldemand_mw"])
                else:
                    if stamp < (MEASURED_START if basis == "measured" else LAST_YEAR):
                        continue
                    load = float(d["measured_mw"])
                    if basis == "underlying":
                        load += float(d["rooftop_mw"])
                year = stamp.year - int(stamp.month < 7)
                writer.writerow([stamp.isoformat(), f"{year}-{year+1}", 1, load,
                                 resource["wind"], resource["solar"]])
    return missing


def analyse(demand_file, resources_file, canonical_dir, output):
    if output.exists():
        raise FileExistsError(output)
    missing = canonical_inputs(demand_file, resources_file, canonical_dir)
    technologies = read_technologies(TECHS)
    with (HISTORICAL / "fleets.csv").open(newline="") as f:
        fleets = {r["design_year"]: np.array([float(r[t.name + "_mw"]) for t in technologies])
                  for r in csv.DictReader(f) if r["design_year"] in {"2003-2004", "joint"}}
    if set(fleets) != {"2003-2004", "joint"}:
        raise ValueError("Missing historical capacity vector")
    old_energy = json.loads((HISTORICAL / "summary.json").read_text())["annual_demand_mwh"]
    dispatch_mean = read_trace(canonical_dir / "dispatch.csv").demand_mw.mean()
    scale = float(old_energy / (8760 * dispatch_mean))
    periods, events = [], []
    cases = [
        ("dispatch", 1.0, "reported"), ("dispatch", scale, "old_mean"),
        ("measured", 1.0, "reported"), ("measured", scale, "same_multiplier"),
        ("underlying", 1.0, "reported"),
    ]
    # Compare all three load definitions at exactly the same full-year energy.
    for basis in ("dispatch", "measured", "underlying"):
        latest = read_trace(canonical_dir / f"{basis}.csv", periods=["2025-2026"])
        cases.append((basis, old_energy / latest.demand_mw.sum(), "old_energy_2025_26"))
    for basis, multiplier, level in cases:
        path = canonical_dir / f"{basis}.csv"
        for year in dict.fromkeys(read_trace(path).periods):
            if level == "old_energy_2025_26" and year != "2025-2026":
                continue
            trace = read_trace(path, periods=[year])
            test = replace(trace, demand_mw=trace.demand_mw * multiplier)
            unknown = np.array([missing[t] / 12 for t in trace.timestamps])
            for fleet, capacity in fleets.items():
                key = {"demand_basis": basis, "demand_scale": level, "period": year, "fleet": fleet}
                metrics, spells = replay(test, technologies, capacity)
                power = np.zeros(len(trace.timestamps))
                extra = np.zeros_like(power)
                wind_mw = np.zeros_like(power)
                for i, t in enumerate(technologies):
                    p = capacity[i] * t.availability * trace.profiles[t.profile]
                    power += p
                    if t.profile == "wind":
                        wind_mw += p
                    if t.profile in ("wind", "solar"):
                        extra += capacity[i] * t.availability * unknown
                margin = power - test.demand_mw
                worst = int(np.argmin(margin))
                loaded = trace.demand_mw > 0
                first_binding = np.min(power[loaded] / trace.demand_mw[loaded])
                shortage = np.maximum(0., -margin)
                upper_supply_shortage = np.maximum(0., -margin - extra)
                if not np.allclose(shortage, upper_supply_shortage, rtol=0, atol=SHORTFALL_TOLERANCE_MW):
                    raise ValueError("Missing five-minute resource observations affect shortage")
                if margin[worst] != (margin + extra).min():
                    raise ValueError("Missing resources affect minimum headroom")
                if first_binding != np.min((power + extra)[loaded] / trace.demand_mw[loaded]):
                    raise ValueError("Missing resources affect the first binding load multiplier")
                if abs(shortage.sum() - metrics["unserved_mwh"]) > 1e-5:
                    raise ValueError("Frozen-fleet shortage energy does not reconcile")
                wind_adjustment = sum(capacity[i] * (1 - t.availability) * trace.profiles[t.profile]
                                      for i, t in enumerate(technologies) if t.profile == "wind")
                no_extra_wind_derating = np.maximum(0., -margin - wind_adjustment)
                periods.append({
                    **key, "hours": len(margin), "load_multiplier": multiplier,
                    "period_demand_mwh": test.demand_mw.sum(), "peak_demand_mw": test.demand_mw.max(),
                    "min_headroom_mw": margin[worst], "tightest_hour_aest": test.timestamps[worst],
                    "demand_at_tightest_mw": test.demand_mw[worst],
                    "wind_cf_at_tightest": trace.profiles["wind"][worst],
                    "solar_cf_at_tightest": trace.profiles["solar"][worst],
                    "wind_at_tightest_mw": wind_mw[worst],
                    "available_at_tightest_mw": power[worst],
                    "load_multiplier_to_first_binding_from_unscaled": first_binding,
                    "max_shortfall_mw": metrics["max_shortfall_mw"],
                    "shortage_hours": metrics["shortage_hours"], "unserved_mwh": metrics["unserved_mwh"],
                    "events": metrics["event_count"],
                    "shortage_hours_wind_avail_1": int(np.sum(no_extra_wind_derating > SHORTFALL_TOLERANCE_MW)),
                    "max_shortfall_mw_wind_avail_1": float(no_extra_wind_derating.max()),
                })
                events.extend(key | spell for spell in spells)

    output.mkdir(parents=True, exist_ok=False)
    event_fields = ["demand_basis", "demand_scale", "period", "fleet", "start", "end_exclusive",
                    "duration_hours", "unserved_mwh", "peak_shortfall_mw", "peak_timestamp",
                    "demand_mw", "wind_profile", "solar_profile", "wind_dispatch_mw",
                    "solar_dispatch_mw", "firm_available_mw"]
    for file, fields, rows in [("periods.csv", periods[0].keys(), periods),
                               ("events.csv", event_fields, events)]:
        with (output / file).open("x", newline="") as f:
            writer = csv.DictWriter(f, fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    inputs = [demand_file, resources_file, HISTORICAL / "fleets.csv", HISTORICAL / "summary.json",
              TECHS, *sorted(canonical_dir.glob("*.csv")), ROOT / "uv.lock",
              *sorted((ROOT / "scripts").glob("modern_*.py")), Path(__file__),
              ROOT / "scripts/weather_replay.py", ROOT / "src/energymod/data.py",
              ROOT / "scripts/fetch_nem_archives.py", ROOT / "data/nem_replay_sources.csv"]
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    provenance = {"python": platform.python_version(), "numpy": np.__version__, "sha256": sources,
                  "start_aest": START.isoformat(), "end_exclusive_aest": STOP.isoformat(),
                  "target_annual_demand_mwh": old_energy, "dispatch_mean_mw": float(dispatch_mean),
                  "old_mean_multiplier": scale,
                  "missing_five_min_by_hour": {t: n for t, n in missing.items() if n}}
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hourly_demand", type=Path)
    parser.add_argument("hourly_resources", type=Path)
    parser.add_argument("canonical_dir", type=Path, help="New directory for local hourly trace CSVs")
    parser.add_argument("output", type=Path, help="New directory for summary tables")
    args = parser.parse_args()
    analyse(args.hourly_demand, args.hourly_resources, args.canonical_dir, args.output)
