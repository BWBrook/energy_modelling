import csv
import gzip
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from energymod.schema import PlanningOptions, Storage, Technology, TraceData


def write_results(folder: Path, trace: TraceData, technologies: list[Technology],
                  solution, audit: dict, options: PlanningOptions,
                  storage: Storage | None, provenance: dict) -> dict:
    weights = trace.annual_weights
    energy = weights @ solution.dispatch_mw
    capacities = []
    for j, tech in enumerate(technologies):
        capacity = float(solution.capacity_mw[j])
        fixed = capacity * tech.annual_fixed_cost_per_mw
        variable = float(energy[j]) * tech.variable_cost_per_mwh
        carbon = float(energy[j]) * tech.co2_t_per_mwh * options.carbon_price_per_t
        available = trace.profiles[tech.profile] * tech.availability * capacity
        capacities.append({
            "technology": tech.name, "nameplate_capacity_mw": capacity,
            "availability": tech.availability, "profile": tech.profile,
            "annual_generation_mwh": float(energy[j]),
            "capacity_factor": float(energy[j] / (capacity * 8760)) if capacity > 1e-9 else None,
            "annual_fixed_cost": fixed, "annual_variable_cost": variable,
            "annual_carbon_cost": carbon, "annual_total_cost": fixed + variable + carbon,
            "cost_per_mwh_generated": (fixed + variable + carbon) / energy[j] if energy[j] > 1e-9 else None,
            "annual_renewable_curtailment_mwh": float(weights @ (available - solution.dispatch_mw[:, j]))
            if tech.profile != "firm" else None,
        })
    _csv(folder / "capacity.csv", capacities)
    period_results = []
    rates = np.array([t.variable_cost_per_mwh + options.carbon_price_per_t * t.co2_t_per_mwh
                       for t in technologies])
    co2 = np.array([t.co2_t_per_mwh for t in technologies])
    fixed_total = audit["annual_fixed_generation_cost"] + audit["annual_storage_fixed_cost"]
    for period in dict.fromkeys(trace.periods):
        rows = np.flatnonzero(np.asarray(trace.periods) == period)
        probability = float(weights[rows].sum() / 8760)
        year_weights = weights[rows] / probability
        demand = float(year_weights @ trace.demand_mw[rows])
        annual_energy = year_weights @ solution.dispatch_mw[rows]
        emissions = float(annual_energy @ co2)
        operating = float(annual_energy @ rates)
        if storage is not None:
            operating += float(year_weights @ solution.discharge_mw[rows]) * storage.variable_cost_per_mwh
        annual_cost = fixed_total + operating
        period_results.append({
            "period": period, "probability": probability, "model_hours": float(trace.duration_hours[rows].sum()),
            "annual_demand_mwh": demand, "annual_generation_mwh": float(annual_energy.sum()),
            "annual_total_cost": annual_cost, "expected_annual_cost_contribution": probability * annual_cost,
            "cost_per_mwh_demand": annual_cost / demand,
            "annual_emissions_t": emissions, "emissions_t_per_mwh_demand": emissions / demand,
            "annual_storage_charge_mwh": float(year_weights @ solution.charge_mw[rows]),
            "annual_storage_discharge_mwh": float(year_weights @ solution.discharge_mw[rows]),
            "max_storage_soc_mwh": float(np.max(solution.soc_mwh[rows])),
        })
        for j, tech in enumerate(technologies):
            period_results[-1][f"annual_generation_{tech.name}_mwh"] = float(annual_energy[j])
        renewable = [j for j, tech in enumerate(technologies) if tech.profile != "firm"]
        renewable_output = solution.dispatch_mw[rows][:, renewable].sum(axis=1)
        curtailed = 0.0
        for j in renewable:
            tech = technologies[j]
            potential = (trace.profiles[tech.profile][rows] * tech.availability *
                         solution.capacity_mw[j])
            curtailed += float(year_weights @ (potential - solution.dispatch_mw[rows, j]))
        period_results[-1]["annual_renewable_curtailment_mwh"] = curtailed
        period_results[-1]["peak_demand_minus_renewable_dispatch_mw"] = float(
            np.max(trace.demand_mw[rows] - renewable_output))
    _csv(folder / "periods.csv", period_results)
    with gzip.open(folder / "dispatch.csv.gz", "wt", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp", "period", "duration_hours", "annual_weight_hours", "demand_mw"] +
                        [f"generation_{t.name}_mw" for t in technologies] +
                        ["charge_mw", "discharge_mw", "soc_end_mwh"])
        for i in range(len(trace.demand_mw)):
            writer.writerow([trace.timestamps[i], trace.periods[i], trace.duration_hours[i],
                             weights[i], trace.demand_mw[i], *solution.dispatch_mw[i],
                             solution.charge_mw[i], solution.discharge_mw[i], solution.soc_mwh[i]])
    summary = {
        "status": "optimal_and_independently_checked", "provenance": provenance,
        "trace": trace.metadata, "planning": asdict(options),
        "technologies": [asdict(t) for t in technologies],
        "storage_assumptions": None if storage is None else asdict(storage),
        "storage_power_mw": float(solution.storage_power_mw),
        "storage_energy_mwh": float(solution.storage_energy_mwh),
        "solver": {"name": "HiGHS bundled with the recorded SciPy distribution",
                   "message": solution.solver_message, "seconds": solution.solve_seconds,
                   "iterations": solution.iterations},
        "accounting": audit,
        "interpretation": [
            "Greenfield single-bus NEM model, continuous capacity and perfect foresight.",
            "Common capacities meet every sampled hour; costs are expected annual costs across the supplied periods.",
            "Availability is constant deterministic output derating, including renewable profiles assumed to describe weather alone.",
            "Thermal plants can dispatch freely from zero to their available output; no commitment, ramping or reserve constraints.",
            "Adequacy for supplied traces does not estimate forced-outage reliability or security.",
            "The optimum is conditional on the supplied assumptions and need not have a unique capacity vector.",
        ],
    }
    (folder / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    return summary


def _csv(path: Path, records: list[dict]) -> None:
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
