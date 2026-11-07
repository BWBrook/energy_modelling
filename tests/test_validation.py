from types import SimpleNamespace

import numpy as np
import pytest

from energymod.schema import PlanningOptions, Storage, Technology, TraceData
from energymod.validation import audit_solution


def fixture():
    trace = TraceData(np.ones(2), {"firm": np.ones(2)}, np.ones(2),
                      np.full(2, 4380.0), ("year", "year"), ("a", "b"))
    tech = Technology("gas", "firm", 8760, 2, 0.5, availability=0.5)
    result = SimpleNamespace(capacity_mw=np.array([2.0]), dispatch_mw=np.ones((2, 1)),
                             storage_power_mw=0, storage_energy_mwh=0,
                             charge_mw=np.zeros(2), discharge_mw=np.zeros(2), soc_mwh=np.zeros(2),
                             objective_cost=35040.0)
    return trace, [tech], result


def test_reconstructs_cost_and_carbon_without_solver():
    trace, tech, result = fixture()
    audit = audit_solution(trace, tech, result, PlanningOptions())
    assert audit["annual_total_cost"] == 35040
    assert audit["annual_emissions_t"] == 4380
    assert audit["cost_per_mwh_demand"] == 4
    result.objective_cost += 100 * 4380
    audit = audit_solution(trace, tech, result, PlanningOptions(carbon_price_per_t=100))
    assert audit["annual_carbon_cost"] == 438000


def test_rejects_wrong_objective_even_when_dispatch_balances():
    trace, tech, result = fixture()
    result.objective_cost = 30000
    with pytest.raises(ValueError, match="objective cost"):
        audit_solution(trace, tech, result, PlanningOptions())


def test_rejects_capacity_and_balance_errors():
    trace, tech, result = fixture()
    result.capacity_mw[0] = 1
    with pytest.raises(ValueError, match="output limit"):
        audit_solution(trace, tech, result, PlanningOptions())
    trace, tech, result = fixture()
    result.dispatch_mw[0, 0] = 0.8
    with pytest.raises(ValueError, match="demand balance"):
        audit_solution(trace, tech, result, PlanningOptions())


def test_rejects_cross_period_energy_borrowing():
    _, tech, result = fixture()
    trace = TraceData(np.ones(2), {"firm": np.ones(2)}, np.ones(2),
                      np.full(2, 4380.0), ("a", "b"), ("a", "b"))
    result.capacity_mw[0] = 4
    result.dispatch_mw[:, 0] = [2, 0]
    result.charge_mw[:] = [1, 0]
    result.discharge_mw[:] = [0, 1]
    result.soc_mwh[:] = [1, 0]
    result.storage_power_mw = result.storage_energy_mwh = 1
    result.objective_cost = 52562
    with pytest.raises(ValueError, match="storage dynamics or period closure"):
        audit_solution(trace, tech, result, PlanningOptions(), Storage(1, 1, 1, 1))


def test_rejects_nonfinite_result():
    trace, tech, result = fixture()
    result.dispatch_mw[0, 0] = np.nan
    with pytest.raises(ValueError, match="nonfinite"):
        audit_solution(trace, tech, result, PlanningOptions())


def test_independent_checker_rejects_forged_emissions_compliance():
    trace, tech, result = fixture()
    with pytest.raises(ValueError, match="emissions constraint"):
        audit_solution(trace, tech, result, PlanningOptions(emissions_limit_t_per_mwh=0.1))
