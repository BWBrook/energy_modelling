"""Fit the eight historical single-year fleets and one joint fleet, then replay them."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from energymod.cli import _provenance, load_config
from energymod.model import solve
from energymod.schema import TraceData
from energymod.validation import audit_solution
from weather_replay import SHORTFALL_TOLERANCE_MW, replay


ROOT = Path(__file__).resolve().parents[1]


def write_table(path, rows):
    with path.open("x", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def weather_years(trace):
    years = {}
    for label in dict.fromkeys(trace.periods):
        indices = np.flatnonzero(np.asarray(trace.periods) == label)
        block = slice(indices[0], indices[-1] + 1)
        durations = trace.duration_hours[block]
        if len(indices) != 8760 or not np.all(durations == 1):
            raise ValueError("Historical weather test requires 8760 hourly intervals per year")
        years[label] = TraceData(
            demand_mw=trace.demand_mw[block],
            profiles={k: v[block] for k, v in trace.profiles.items()},
            duration_hours=durations, annual_weights=durations,
            periods=trace.periods[block], timestamps=trace.timestamps[block],
        )
    reference = next(iter(years.values())).demand_mw
    if len(years) != 8 or any(not np.array_equal(y.demand_mw, reference) for y in years.values()):
        raise ValueError("Expected eight weather years paired with the same hourly demand")
    return years


def run(output):
    if output.exists():
        raise FileExistsError(output)
    config, trace, techs, options, storage, paths = load_config(ROOT / "config/historical.toml")
    if storage or options.emissions_limit_t_per_mwh is not None or options.carbon_price_per_t:
        raise ValueError("Merit-order replay requires the historical generation-only assumptions")
    years = weather_years(trace)
    provenance = _provenance(paths, config)
    provenance["analysis_sha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (Path(__file__), ROOT / "scripts/weather_replay.py")
    }
    fleets, pairs, events, joint_replays = [], [], [], []
    for label, design in [*years.items(), ("joint", trace)]:
        solution = solve(design, techs, options)
        audit = audit_solution(design, techs, solution, options)
        fleet = {
            "design_year": label,
            **{f"{t.name}_mw": float(k) for t, k in zip(techs, solution.capacity_mw, strict=True)},
            "annual_fixed_cost": audit["annual_fixed_generation_cost"],
            "annual_variable_cost": audit["annual_variable_generation_cost"],
            "annual_cost": audit["annual_total_cost"],
            "solver_objective": solution.objective_cost,
            "max_balance_residual_mw": audit["max_hourly_balance_residual_mw"],
            "solver_status": solution.solver_message,
        }
        fleets.append(fleet)
        for weather, test in years.items():
            metrics, spells = replay(test, techs, solution.capacity_mw)
            labels = {"design_year": label, "weather_year": weather}
            row = labels | metrics
            (joint_replays if label == "joint" else pairs).append(row)
            events.extend(labels | spell for spell in spells)
            if (label == weather or label == "joint") and row["shortage_hours"]:
                raise ValueError(f"Unexpected within-design shortfall for {labels}")
            if label == weather and abs(row["annual_cost"] - fleet["annual_cost"]) > 1:
                raise ValueError(f"Own-year replay cost differs from the fit for {label}")
        print(f"{label} independently checked", flush=True)

    joint_cost = fleets[-1]["annual_cost"]
    if abs(joint_cost - np.mean([r["annual_cost"] for r in joint_replays])) > 1:
        raise ValueError("Joint expected cost differs from the eight fixed-capacity replays")
    annual_demand = float(next(iter(years.values())).demand_mw.sum())
    mean_single_cost = float(np.mean([f["annual_cost"] for f in fleets[:-1]]))
    premium = joint_cost - mean_single_cost
    if premium < -1:
        raise ValueError("Common-fleet cost falls below the perfect-information lower bound")
    summary = {
        "annual_demand_mwh": annual_demand, "shortfall_threshold_mw": SHORTFALL_TOLERANCE_MW,
        "failed_off_diagonal": sum(r["shortage_hours"] > 0 for r in pairs if r["weather_year"] != r["design_year"]),
        "off_diagonal_tests": len(pairs) - len(years),
        "mean_single_year_optimum_cost": mean_single_cost, "joint_expected_annual_cost": joint_cost,
        "annual_premium": premium, "premium_per_mwh": premium / annual_demand,
        "premium_percent_of_single_year_mean": 100 * premium / mean_single_cost,
    }
    output.mkdir(parents=True, exist_ok=False)
    write_table(output / "fleets.csv", fleets)
    write_table(output / "pairs.csv", pairs)
    write_table(output / "joint_replay.csv", joint_replays)
    if events:
        write_table(output / "events.csv", events)
    for name, data in [("summary", summary), ("provenance", provenance)]:
        (output / f"{name}.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New directory for the result tables")
    run(parser.parse_args().output)
