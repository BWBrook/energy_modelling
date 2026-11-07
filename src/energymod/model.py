"""Sparse linear capacity-expansion model.

The formulation is deliberately small: one electrical bus, continuous shared
capacity decisions, and chronological dispatch for each empirical period.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Sequence

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix, csr_matrix, vstack

from .schema import PlanningOptions, Storage, Technology, TraceData


@dataclass(frozen=True)
class Solution:
    """Optimal annual plan and its period-specific operation."""

    capacity_mw: np.ndarray
    dispatch_mw: np.ndarray
    storage_power_mw: float
    storage_energy_mwh: float
    charge_mw: np.ndarray
    discharge_mw: np.ndarray
    soc_mwh: np.ndarray
    objective_cost: float
    solver_message: str
    solve_seconds: float
    iterations: int


def _matrix(
    rows: np.ndarray,
    columns: np.ndarray,
    values: np.ndarray,
    shape: tuple[int, int],
) -> csr_matrix:
    return coo_matrix((values, (rows, columns)), shape=shape).tocsr()


def solve(
    trace: TraceData,
    technologies: Sequence[Technology],
    options: PlanningOptions = PlanningOptions(),
    storage: Storage | None = None,
) -> Solution:
    """Minimise expected annual cost subject to every hourly energy balance.

    Generation capacities are nameplate MW shared by all empirical periods.
    Dispatch and, when enabled, storage operation are period-specific recourse.
    """

    technologies = tuple(technologies)
    if not technologies:
        raise ValueError("At least one technology is required")
    names = [technology.name for technology in technologies]
    if len(names) != len(set(names)):
        raise ValueError("Technology names must be unique")
    missing = sorted({technology.profile for technology in technologies} - trace.profiles.keys())
    if missing:
        raise ValueError(f"Missing generation profiles: {', '.join(missing)}")

    n_time = len(trace.demand_mw)
    n_tech = len(technologies)
    n_dispatch = n_time * n_tech
    capacity_start = 0
    dispatch_start = n_tech
    if storage is None:
        power_index = energy_index = charge_start = discharge_start = soc_start = None
        n_variables = n_tech + n_dispatch
    else:
        power_index = n_tech + n_dispatch
        energy_index = power_index + 1
        charge_start = energy_index + 1
        discharge_start = charge_start + n_time
        soc_start = discharge_start + n_time
        n_variables = soc_start + n_time

    objective = np.zeros(n_variables)
    objective[capacity_start:dispatch_start] = [
        technology.annual_fixed_cost_per_mw for technology in technologies
    ]
    marginal_cost = np.asarray(
        [
            technology.variable_cost_per_mwh
            + options.carbon_price_per_t * technology.co2_t_per_mwh
            for technology in technologies
        ]
    )
    objective[dispatch_start : dispatch_start + n_dispatch] = (
        trace.annual_weights[:, None] * marginal_cost[None, :]
    ).ravel()
    if storage is not None:
        objective[power_index] = storage.annual_power_cost_per_mw
        objective[energy_index] = storage.annual_energy_cost_per_mwh
        objective[discharge_start:soc_start] = (
            trace.annual_weights * storage.variable_cost_per_mwh
        )

    bounds: list[tuple[float, float | None]] = [
        (technology.min_capacity_mw, technology.max_capacity_mw)
        for technology in technologies
    ]
    bounds.extend([(0.0, None)] * n_dispatch)
    if storage is not None:
        bounds.extend(
            [
                (0.0, storage.max_power_mw),
                (0.0, storage.max_energy_mwh),
            ]
        )
        bounds.extend([(0.0, None)] * (3 * n_time))

    # Exact nodal energy balance for every snapshot.
    balance_rows = np.repeat(np.arange(n_time), n_tech)
    balance_columns = dispatch_start + np.arange(n_dispatch)
    balance_values = np.ones(n_dispatch)
    if storage is not None:
        balance_rows = np.concatenate((balance_rows, np.arange(n_time), np.arange(n_time)))
        balance_columns = np.concatenate(
            (
                balance_columns,
                discharge_start + np.arange(n_time),
                charge_start + np.arange(n_time),
            )
        )
        balance_values = np.concatenate(
            (balance_values, np.ones(n_time), -np.ones(n_time))
        )
    a_eq_parts = [_matrix(balance_rows, balance_columns, balance_values, (n_time, n_variables))]
    b_eq_parts = [trace.demand_mw]

    if storage is not None:
        # SOC is the state at the end of each snapshot. The first state in a
        # period refers back to the last state of that same period.
        period_array = np.asarray(trace.periods)
        predecessor = np.arange(n_time) - 1
        starts = np.flatnonzero(np.r_[True, period_array[1:] != period_array[:-1]])
        ends = np.r_[starts[1:] - 1, n_time - 1]
        predecessor[starts] = ends
        soc_rows = np.tile(np.arange(n_time), 4)
        soc_columns = np.concatenate(
            (
                soc_start + np.arange(n_time),
                soc_start + predecessor,
                charge_start + np.arange(n_time),
                discharge_start + np.arange(n_time),
            )
        )
        soc_values = np.concatenate(
            (
                np.ones(n_time),
                -np.ones(n_time),
                -storage.charge_efficiency * trace.duration_hours,
                trace.duration_hours / storage.discharge_efficiency,
            )
        )
        a_eq_parts.append(_matrix(soc_rows, soc_columns, soc_values, (n_time, n_variables)))
        b_eq_parts.append(np.zeros(n_time))

    a_eq = vstack(a_eq_parts, format="csr")
    b_eq = np.concatenate(b_eq_parts)

    # Generation cannot exceed nameplate capacity times deterministic
    # availability and the snapshot resource profile.
    limit_rows = np.arange(n_dispatch)
    time_index = np.repeat(np.arange(n_time), n_tech)
    tech_index = np.tile(np.arange(n_tech), n_time)
    profiles = np.column_stack(
        [trace.profiles[technology.profile] for technology in technologies]
    )
    availability = np.asarray([technology.availability for technology in technologies])
    limit_columns = np.concatenate(
        (
            dispatch_start + np.arange(n_dispatch),
            tech_index,
        )
    )
    limit_values = np.concatenate(
        (
            np.ones(n_dispatch),
            -(profiles * availability[None, :]).ravel(),
        )
    )
    a_ub_parts = [
        _matrix(
            np.concatenate((limit_rows, limit_rows)),
            limit_columns,
            limit_values,
            (n_dispatch, n_variables),
        )
    ]
    b_ub_parts = [np.zeros(n_dispatch)]

    if storage is not None:
        storage_rows = np.arange(n_time * 3)
        storage_columns = np.concatenate(
            (
                charge_start + np.arange(n_time),
                discharge_start + np.arange(n_time),
                soc_start + np.arange(n_time),
                np.full(n_time, power_index),
                np.full(n_time, power_index),
                np.full(n_time, energy_index),
            )
        )
        storage_values = np.concatenate(
            (
                np.ones(3 * n_time),
                -np.ones(3 * n_time),
            )
        )
        a_ub_parts.append(
            _matrix(
                np.concatenate((storage_rows, storage_rows)),
                storage_columns,
                storage_values,
                (n_time * 3, n_variables),
            )
        )
        b_ub_parts.append(np.zeros(n_time * 3))

    if options.emissions_limit_t_per_mwh is not None:
        emissions = np.asarray([technology.co2_t_per_mwh for technology in technologies])
        if options.emissions_limit_scope == "expected":
            emissions_rows = np.zeros(n_dispatch, dtype=int)
            emissions_values = (trace.annual_weights[:, None] * emissions[None, :]).ravel()
            a_ub_parts.append(
                _matrix(
                    emissions_rows,
                    dispatch_start + np.arange(n_dispatch),
                    emissions_values,
                    (1, n_variables),
                )
            )
            b_ub_parts.append(
                np.asarray(
                    [
                        options.emissions_limit_t_per_mwh
                        * np.dot(trace.annual_weights, trace.demand_mw)
                    ]
                )
            )
        else:
            period_array = np.asarray(trace.periods)
            period_names = tuple(dict.fromkeys(trace.periods))
            emissions_row_blocks = []
            emissions_column_blocks = []
            emissions_value_blocks = []
            emission_bounds = []
            for row, period in enumerate(period_names):
                selected_times = np.flatnonzero(period_array == period)
                selected_dispatch = (
                    selected_times[:, None] * n_tech + np.arange(n_tech)[None, :]
                ).ravel()
                emissions_row_blocks.append(np.full(len(selected_dispatch), row))
                emissions_column_blocks.append(dispatch_start + selected_dispatch)
                emissions_value_blocks.append(
                    (
                        trace.annual_weights[selected_times, None] * emissions[None, :]
                    ).ravel()
                )
                emission_bounds.append(
                    options.emissions_limit_t_per_mwh
                    * np.dot(trace.annual_weights[selected_times], trace.demand_mw[selected_times])
                )
            a_ub_parts.append(
                _matrix(
                    np.concatenate(emissions_row_blocks),
                    np.concatenate(emissions_column_blocks),
                    np.concatenate(emissions_value_blocks),
                    (len(period_names), n_variables),
                )
            )
            b_ub_parts.append(np.asarray(emission_bounds))

    a_ub = vstack(a_ub_parts, format="csr")
    b_ub = np.concatenate(b_ub_parts)

    started = perf_counter()
    result = linprog(
        objective,
        A_ub=a_ub,
        b_ub=b_ub,
        A_eq=a_eq,
        b_eq=b_eq,
        bounds=bounds,
        method=options.solver_method,
        options={"time_limit": options.time_limit_seconds},
    )
    elapsed = perf_counter() - started
    if not result.success:
        categories = {
            1: "time or iteration limit",
            2: "infeasible",
            3: "unbounded",
            4: "solver failure",
        }
        category = categories.get(result.status, "unknown solver failure")
        raise RuntimeError(f"Optimisation {category} (status {result.status}): {result.message}")

    values = result.x
    capacity = values[:n_tech].copy()
    dispatch = values[dispatch_start : dispatch_start + n_dispatch].reshape(n_time, n_tech)
    if storage is None:
        power = energy = 0.0
        charge = np.zeros(n_time)
        discharge = np.zeros(n_time)
        soc = np.zeros(n_time)
    else:
        power = float(values[power_index])
        energy = float(values[energy_index])
        charge = values[charge_start:discharge_start].copy()
        discharge = values[discharge_start:soc_start].copy()
        soc = values[soc_start:].copy()
    return Solution(
        capacity_mw=capacity,
        dispatch_mw=dispatch.copy(),
        storage_power_mw=power,
        storage_energy_mwh=energy,
        charge_mw=charge,
        discharge_mw=discharge,
        soc_mwh=soc,
        objective_cost=float(result.fun),
        solver_message=result.message,
        solve_seconds=elapsed,
        iterations=int(result.nit),
    )
