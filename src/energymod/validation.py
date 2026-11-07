from typing import Any

import numpy as np

from energymod.schema import PlanningOptions, Storage, Technology, TraceData


def audit_solution(trace: TraceData, technologies: list[Technology], solution: Any,
                   options: PlanningOptions, storage: Storage | None = None,
                   atol: float = 1e-5, rtol: float = 1e-8) -> dict:
    """Reconstruct physical and financial balances without the solver matrices."""
    n, k = len(trace.demand_mw), len(technologies)
    capacity = np.asarray(solution.capacity_mw)
    dispatch = np.asarray(solution.dispatch_mw)
    charge = np.asarray(solution.charge_mw)
    discharge = np.asarray(solution.discharge_mw)
    soc = np.asarray(solution.soc_mwh)
    if capacity.shape != (k,) or dispatch.shape != (n, k):
        raise ValueError("Solution generation dimensions do not match the model")
    if any(x.shape != (n,) for x in (charge, discharge, soc)):
        raise ValueError("Solution storage dimensions do not match the trace")
    all_values = np.r_[capacity, dispatch.ravel(), charge, discharge, soc,
                       solution.storage_power_mw, solution.storage_energy_mwh,
                       solution.objective_cost]
    if not np.all(np.isfinite(all_values)):
        raise ValueError("Solution contains nonfinite values")
    errors = []
    warnings = []

    def bound(name: str, residual: np.ndarray | float, scale: np.ndarray | float) -> None:
        if np.any(np.asarray(residual) > atol + rtol * np.maximum(1, np.abs(scale))):
            errors.append(name)

    bound("negative generation or capacity", -np.r_[capacity, dispatch.ravel()], 1)
    for j, tech in enumerate(technologies):
        bound(f"minimum capacity: {tech.name}", tech.min_capacity_mw - capacity[j], capacity[j])
        if tech.max_capacity_mw is not None:
            bound(f"maximum capacity: {tech.name}", capacity[j] - tech.max_capacity_mw,
                  tech.max_capacity_mw)
    available = np.column_stack([trace.profiles[t.profile] * t.availability * capacity[j]
                                 for j, t in enumerate(technologies)])
    bound("generator output limit", dispatch - available, available)
    balance = dispatch.sum(axis=1) + discharge - charge - trace.demand_mw
    bound("hourly demand balance", np.abs(balance), trace.demand_mw)
    storage_residual = np.zeros(n)
    bound("negative storage values", -np.r_[charge, discharge, soc,
                                            solution.storage_power_mw,
                                            solution.storage_energy_mwh], 1)
    if storage is None:
        bound("storage exists when disabled", np.abs(np.r_[charge, discharge, soc,
                                                           solution.storage_power_mw,
                                                           solution.storage_energy_mwh]), 1)
    else:
        bound("storage charging power", charge - solution.storage_power_mw,
              solution.storage_power_mw)
        bound("storage discharging power", discharge - solution.storage_power_mw,
              solution.storage_power_mw)
        bound("storage energy capacity", soc - solution.storage_energy_mwh,
              solution.storage_energy_mwh)
        if storage.max_power_mw is not None:
            bound("maximum storage power", solution.storage_power_mw - storage.max_power_mw,
                  storage.max_power_mw)
        if storage.max_energy_mwh is not None:
            bound("maximum storage energy", solution.storage_energy_mwh - storage.max_energy_mwh,
                  storage.max_energy_mwh)
        for period in dict.fromkeys(trace.periods):
            rows = np.flatnonzero(np.asarray(trace.periods) == period)
            previous = np.roll(soc[rows], 1)
            storage_residual[rows] = (soc[rows] - previous - storage.charge_efficiency *
                                      charge[rows] * trace.duration_hours[rows] +
                                      discharge[rows] * trace.duration_hours[rows] /
                                      storage.discharge_efficiency)
        bound("storage dynamics or period closure", np.abs(storage_residual),
              solution.storage_energy_mwh)
        if np.max(np.minimum(charge, discharge)) > atol:
            warnings.append("Simultaneous charging and discharging occurs in the continuous LP solution")
    weights = trace.annual_weights
    energy = weights @ dispatch
    fuel_cost = float(energy @ np.array([t.variable_cost_per_mwh for t in technologies]))
    emissions = float(energy @ np.array([t.co2_t_per_mwh for t in technologies]))
    fixed_cost = float(capacity @ np.array([t.annual_fixed_cost_per_mw for t in technologies]))
    storage_fixed = 0.0 if storage is None else (
        solution.storage_power_mw * storage.annual_power_cost_per_mw +
        solution.storage_energy_mwh * storage.annual_energy_cost_per_mwh)
    storage_variable = 0.0 if storage is None else (
        float(weights @ discharge) * storage.variable_cost_per_mwh)
    carbon_cost = emissions * options.carbon_price_per_t
    reconstructed = fixed_cost + fuel_cost + carbon_cost + storage_fixed + storage_variable
    bound("objective cost reconciliation", abs(reconstructed - solution.objective_cost), reconstructed)
    demand = float(weights @ trace.demand_mw)
    if options.emissions_limit_t_per_mwh is not None:
        scopes = [np.arange(n)] if options.emissions_limit_scope == "expected" else [
            np.flatnonzero(np.asarray(trace.periods) == period)
            for period in dict.fromkeys(trace.periods)]
        for rows in scopes:
            actual = float(weights[rows] @ dispatch[rows] @
                           np.array([t.co2_t_per_mwh for t in technologies]))
            allowed = options.emissions_limit_t_per_mwh * float(weights[rows] @ trace.demand_mw[rows])
            bound("emissions constraint", actual - allowed, allowed)
    if errors:
        raise ValueError("Independent solution audit failed: " + "; ".join(errors))
    return {
        "passed": True,
        "absolute_tolerance": atol,
        "relative_tolerance": rtol,
        "max_hourly_balance_residual_mw": float(np.max(np.abs(balance))),
        "max_generation_limit_excess_mw": float(max(0, np.max(dispatch - available))),
        "max_storage_equation_residual_mwh": float(np.max(np.abs(storage_residual))),
        "max_simultaneous_storage_mw": float(np.max(np.minimum(charge, discharge))),
        "objective_reconstruction_error": float(abs(reconstructed - solution.objective_cost)),
        "annual_demand_mwh": demand,
        "annual_generation_mwh": float(energy.sum()),
        "annual_storage_charge_mwh": float(weights @ charge),
        "annual_storage_discharge_mwh": float(weights @ discharge),
        "annual_storage_loss_mwh": float(weights @ (charge - discharge)),
        "annual_fixed_generation_cost": fixed_cost,
        "annual_variable_generation_cost": fuel_cost,
        "annual_carbon_cost": carbon_cost,
        "annual_storage_fixed_cost": float(storage_fixed),
        "annual_storage_variable_cost": storage_variable,
        "annual_total_cost": float(reconstructed),
        "cost_per_mwh_demand": float(reconstructed / demand),
        "annual_emissions_t": emissions,
        "emissions_t_per_mwh_demand": float(emissions / demand),
        "warnings": warnings,
    }
