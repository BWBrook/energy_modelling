import numpy as np
import pytest

from energymod.model import solve
from energymod.schema import PlanningOptions, Storage, Technology, TraceData


def trace(demand, profiles, periods=None, durations=None):
    demand = np.asarray(demand, dtype=float)
    n = len(demand)
    durations = np.ones(n) if durations is None else np.asarray(durations, dtype=float)
    periods = tuple(["year"] * n if periods is None else periods)
    names = tuple(dict.fromkeys(periods))
    weights = np.empty(n)
    for name in names:
        selected = np.asarray(periods) == name
        weights[selected] = durations[selected] * (8760 / len(names) / durations[selected].sum())
    return TraceData(
        demand_mw=demand,
        profiles={name: np.asarray(values, dtype=float) for name, values in profiles.items()},
        duration_hours=durations,
        annual_weights=weights,
        periods=periods,
        timestamps=tuple(f"t{i}" for i in range(n)),
    )


def technology(
    name,
    profile="firm",
    fixed=1000,
    variable=0,
    co2=0,
    availability=1,
    minimum=0,
    maximum=None,
):
    return Technology(
        name=name,
        profile=profile,
        annual_fixed_cost_per_mw=fixed,
        variable_cost_per_mwh=variable,
        co2_t_per_mwh=co2,
        availability=availability,
        min_capacity_mw=minimum,
        max_capacity_mw=maximum,
    )


def test_constant_gas_closed_form_and_availability_derating():
    data = trace([100, 100], {"firm": [1, 1]})
    gas = technology("gas", fixed=1000, variable=50, co2=0.6, availability=0.8)
    result = solve(data, [gas])
    assert result.capacity_mw[0] == pytest.approx(125)
    assert result.dispatch_mw[:, 0] == pytest.approx([100, 100])
    assert result.objective_cost == pytest.approx(125 * 1000 + 100 * 8760 * 50)


def test_exact_renewable_match_and_curtailment_are_accounted_hourly():
    match = trace([50, 100], {"wind": [0.5, 1], "firm": [1, 1]})
    wind = technology("wind", "wind", fixed=1000)
    gas = technology("gas", fixed=1000, variable=1000)
    exact = solve(match, [wind, gas])
    assert exact.capacity_mw[0] == pytest.approx(100)
    assert exact.dispatch_mw[:, 0] == pytest.approx([50, 100])
    assert exact.dispatch_mw[:, 1] == pytest.approx([0, 0])

    curtailed = trace([50, 50], {"wind": [1, 0.5], "firm": [1, 1]})
    result = solve(curtailed, [wind, gas])
    assert result.capacity_mw[0] == pytest.approx(100)
    assert result.dispatch_mw[:, 0] == pytest.approx([50, 50])
    assert np.all(result.dispatch_mw[:, 0] <= result.capacity_mw[0] * curtailed.profiles["wind"])


def test_minimum_idle_capacity_still_incurs_fixed_cost():
    data = trace([10], {"firm": [1], "idle": [0]})
    gas = technology("gas", fixed=100, variable=2)
    idle = technology("idle", "idle", fixed=500, minimum=3)
    result = solve(data, [gas, idle])
    expected = 10 * 100 + 10 * 8760 * 2 + 3 * 500
    assert result.capacity_mw == pytest.approx([10, 3])
    assert result.dispatch_mw[0] == pytest.approx([10, 0])
    assert result.objective_cost == pytest.approx(expected)


def test_carbon_price_increment_equals_annual_emissions_times_price():
    data = trace([20, 40], {"firm": [1, 1]})
    gas = technology("gas", fixed=100, variable=5, co2=0.5)
    base = solve(data, [gas])
    priced = solve(data, [gas], PlanningOptions(carbon_price_per_t=80))
    annual_emissions = np.sum(data.annual_weights * base.dispatch_mw[:, 0] * 0.5)
    assert priced.objective_cost - base.objective_cost == pytest.approx(80 * annual_emissions)


def test_expected_emissions_cap_binds_and_impossible_cap_fails():
    data = trace([100, 100], {"firm": [1, 1]})
    dirty = technology("dirty", fixed=1, variable=0, co2=1)
    clean = technology("clean", fixed=1, variable=100, co2=0)
    result = solve(
        data,
        [dirty, clean],
        PlanningOptions(emissions_limit_t_per_mwh=0.5, solver_method="highs-ipm"),
    )
    emissions = np.sum(data.annual_weights[:, None] * result.dispatch_mw * [1, 0])
    demand = np.dot(data.annual_weights, data.demand_mw)
    assert emissions / demand == pytest.approx(0.5)
    with pytest.raises(RuntimeError, match="infeasible"):
        solve(data, [dirty], PlanningOptions(emissions_limit_t_per_mwh=0.5))


def test_per_period_emissions_cap_applies_to_each_empirical_year():
    data = trace(
        [100, 100],
        {"dirty_profile": [1, 0], "firm": [1, 1]},
        periods=("a", "b"),
    )
    dirty = technology("dirty", "dirty_profile", fixed=1, co2=1)
    clean = technology("clean", fixed=1, variable=100)
    expected = solve(
        data,
        [dirty, clean],
        PlanningOptions(emissions_limit_t_per_mwh=0.5, emissions_limit_scope="expected"),
    )
    assert expected.dispatch_mw[:, 0] == pytest.approx([100, 0])
    constrained = solve(
        data,
        [dirty, clean],
        PlanningOptions(emissions_limit_t_per_mwh=0.25, emissions_limit_scope="per_period"),
    )
    assert constrained.dispatch_mw[:, 0] == pytest.approx([25, 0])


def test_demand_scaling_and_duplicated_weather_leave_unit_cost_unchanged():
    base = trace([20, 40], {"firm": [1, 1]})
    doubled = trace([40, 80], {"firm": [1, 1]})
    tech = technology("gas", fixed=200, variable=30)
    first = solve(base, [tech])
    second = solve(doubled, [tech])
    assert second.capacity_mw == pytest.approx(2 * first.capacity_mw)
    assert second.objective_cost == pytest.approx(2 * first.objective_cost)

    duplicate = trace(
        [20, 40, 20, 40],
        {"firm": [1, 1, 1, 1]},
        periods=("a", "a", "b", "b"),
    )
    repeated = solve(duplicate, [tech])
    assert repeated.capacity_mw == pytest.approx(first.capacity_mw)
    assert repeated.objective_cost == pytest.approx(first.objective_cost)


def test_technology_order_does_not_change_solution_or_objective():
    data = trace([50, 100], {"wind": [1, 0.2], "firm": [1, 1]})
    wind = technology("wind", "wind", fixed=10)
    gas = technology("gas", fixed=100, variable=100)
    forward = solve(data, [wind, gas])
    reverse = solve(data, [gas, wind])
    assert forward.objective_cost == pytest.approx(reverse.objective_cost)
    assert dict(zip(("wind", "gas"), forward.capacity_mw, strict=True)) == pytest.approx(
        dict(zip(("gas", "wind"), reverse.capacity_mw, strict=True))
    )


def test_tiny_solution_matches_exhaustive_capacity_enumeration():
    data = trace([10, 20], {"wind": [1, 0.5], "firm": [1, 1]})
    wind = technology("wind", "wind", fixed=100)
    gas = technology("gas", fixed=100, variable=20)
    result = solve(data, [wind, gas])

    def cost(wind_capacity):
        wind_dispatch = np.minimum(data.demand_mw, wind_capacity * data.profiles["wind"])
        gas_dispatch = data.demand_mw - wind_dispatch
        gas_capacity = gas_dispatch.max()
        return (
            wind_capacity * 100
            + gas_capacity * 100
            + np.dot(data.annual_weights, gas_dispatch) * 20
        )

    grid = np.linspace(0, 40, 4001)
    grid_costs = np.asarray([cost(value) for value in grid])
    assert result.objective_cost == pytest.approx(grid_costs.min(), abs=1e-5)
    assert result.capacity_mw[0] == pytest.approx(grid[grid_costs.argmin()], abs=0.01)


def test_storage_is_cyclic_and_includes_round_trip_losses():
    data = trace([0, 1], {"solar": [1, 0]})
    solar = technology("solar", "solar", fixed=100)
    battery = Storage(
        annual_power_cost_per_mw=10,
        annual_energy_cost_per_mwh=10,
        charge_efficiency=0.8,
        discharge_efficiency=0.8,
        variable_cost_per_mwh=1,
    )
    result = solve(data, [solar], storage=battery)
    assert result.capacity_mw[0] == pytest.approx(1 / 0.64)
    assert result.charge_mw == pytest.approx([1 / 0.64, 0])
    assert result.discharge_mw == pytest.approx([0, 1])
    assert result.soc_mwh == pytest.approx([1.25, 0])
    assert result.storage_power_mw == pytest.approx(1 / 0.64)
    assert result.storage_energy_mwh == pytest.approx(1.25)
    assert np.max(np.minimum(result.charge_mw, result.discharge_mw)) < 1e-8


def test_storage_duration_and_period_boundaries_are_physical():
    data = trace([0, 2], {"solar": [1, 0]}, durations=[2, 1])
    solar = technology("solar", "solar", fixed=100)
    battery = Storage(10, 10, 1, 1, variable_cost_per_mwh=1)
    result = solve(data, [solar], storage=battery)
    assert result.charge_mw == pytest.approx([1, 0])
    assert result.discharge_mw == pytest.approx([0, 2])
    assert result.soc_mwh == pytest.approx([2, 0])

    separated = trace(
        [0, 0, 1, 0],
        {"solar": [1, 0, 0, 0]},
        periods=("a", "a", "b", "b"),
    )
    with pytest.raises(RuntimeError, match="infeasible"):
        solve(separated, [solar], storage=battery)


def test_unused_storage_reproduces_generation_only_solution():
    data = trace([10, 20], {"firm": [1, 1]})
    gas = technology("gas", fixed=100, variable=20)
    base = solve(data, [gas])
    expensive = Storage(
        annual_power_cost_per_mw=1e9,
        annual_energy_cost_per_mwh=1e9,
        charge_efficiency=0.9,
        discharge_efficiency=0.9,
        variable_cost_per_mwh=1,
    )
    with_storage = solve(
        data,
        [gas],
        options=PlanningOptions(solver_method="highs-ipm"),
        storage=expensive,
    )
    assert with_storage.capacity_mw == pytest.approx(base.capacity_mw)
    assert with_storage.dispatch_mw == pytest.approx(base.dispatch_mw)
    assert with_storage.objective_cost == pytest.approx(base.objective_cost)
    assert with_storage.storage_power_mw == pytest.approx(0)
    assert with_storage.storage_energy_mwh == pytest.approx(0)


def test_unbounded_free_storage_capacity_is_rejected_by_schema():
    with pytest.raises(ValueError, match="power cost"):
        Storage(0, 1, 1, 1)
    with pytest.raises(ValueError, match="energy cost"):
        Storage(1, 0, 1, 1)
