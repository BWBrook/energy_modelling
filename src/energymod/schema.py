from dataclasses import dataclass, field
from typing import Any

import numpy as np


def _nonnegative(name: str, value: float) -> None:
    if not np.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")


@dataclass(frozen=True)
class Technology:
    name: str
    profile: str
    annual_fixed_cost_per_mw: float
    variable_cost_per_mwh: float
    co2_t_per_mwh: float
    availability: float = 1.0
    min_capacity_mw: float = 0.0
    max_capacity_mw: float | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.profile:
            raise ValueError("Technology name and profile are required")
        for name in ("annual_fixed_cost_per_mw", "variable_cost_per_mwh", "co2_t_per_mwh",
                     "min_capacity_mw"):
            _nonnegative(name, getattr(self, name))
        if not np.isfinite(self.availability) or not 0 < self.availability <= 1:
            raise ValueError("availability must be in (0, 1]")
        if self.max_capacity_mw is not None:
            _nonnegative("max_capacity_mw", self.max_capacity_mw)
            if self.max_capacity_mw < self.min_capacity_mw:
                raise ValueError("max_capacity_mw is below min_capacity_mw")
        elif self.annual_fixed_cost_per_mw == 0:
            raise ValueError("An expandable technology needs positive fixed cost or a finite capacity bound")


@dataclass(frozen=True)
class Storage:
    annual_power_cost_per_mw: float
    annual_energy_cost_per_mwh: float
    charge_efficiency: float
    discharge_efficiency: float
    variable_cost_per_mwh: float = 0.0
    max_power_mw: float | None = None
    max_energy_mwh: float | None = None

    def __post_init__(self) -> None:
        for name in ("annual_power_cost_per_mw", "annual_energy_cost_per_mwh",
                     "variable_cost_per_mwh"):
            _nonnegative(name, getattr(self, name))
        for name in ("charge_efficiency", "discharge_efficiency"):
            value = getattr(self, name)
            if not np.isfinite(value) or not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        for name in ("max_power_mw", "max_energy_mwh"):
            if getattr(self, name) is not None:
                _nonnegative(name, getattr(self, name))
        if self.annual_power_cost_per_mw == 0 and self.max_power_mw is None:
            raise ValueError("Storage needs positive power cost or a finite power bound")
        if self.annual_energy_cost_per_mwh == 0 and self.max_energy_mwh is None:
            raise ValueError("Storage needs positive energy cost or a finite energy bound")


@dataclass(frozen=True)
class TraceData:
    demand_mw: np.ndarray
    profiles: dict[str, np.ndarray]
    duration_hours: np.ndarray
    annual_weights: np.ndarray
    periods: tuple[str, ...]
    timestamps: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        demand = np.asarray(self.demand_mw, dtype=float)
        duration = np.asarray(self.duration_hours, dtype=float)
        weights = np.asarray(self.annual_weights, dtype=float)
        object.__setattr__(self, "demand_mw", demand)
        object.__setattr__(self, "duration_hours", duration)
        object.__setattr__(self, "annual_weights", weights)
        if demand.ndim != 1 or len(demand) == 0:
            raise ValueError("demand_mw must be a nonempty vector")
        n = len(demand)
        if any(x.shape != (n,) for x in (duration, weights)):
            raise ValueError("Duration and weight vectors must match demand")
        if len(self.periods) != n or len(self.timestamps) != n:
            raise ValueError("Periods and timestamps must match demand")
        if not np.all(np.isfinite(demand)) or np.any(demand < 0) or not np.any(demand > 0):
            raise ValueError("Demand must be finite, nonnegative and positive somewhere")
        for name, values in (("duration_hours", duration), ("annual_weights", weights)):
            if not np.all(np.isfinite(values)) or np.any(values <= 0):
                raise ValueError(f"{name} must be finite and positive")
        if not np.isclose(weights.sum(), 8760, rtol=0, atol=1e-6):
            raise ValueError("annual_weights must sum to 8760 hours")
        seen = set()
        previous = None
        for period in self.periods:
            if not period:
                raise ValueError("Each snapshot needs a period")
            if period != previous:
                if period in seen:
                    raise ValueError("Each period must occupy a contiguous block")
                seen.add(period)
                previous = period
        for period in seen:
            selected = np.asarray(self.periods) == period
            rate = weights[selected] / duration[selected]
            if not np.allclose(rate, rate[0], rtol=1e-10, atol=1e-10):
                raise ValueError("Annual weights must be proportional to duration within each period")
        converted = {}
        for name, values in self.profiles.items():
            array = np.asarray(values, dtype=float)
            if array.shape != (n,) or not np.all(np.isfinite(array)):
                raise ValueError(f"Profile {name} must be finite and match demand")
            if np.any(array < 0) or np.any(array > 1):
                raise ValueError(f"Profile {name} must lie in [0, 1]")
            converted[name] = array
        object.__setattr__(self, "profiles", converted)


@dataclass(frozen=True)
class PlanningOptions:
    carbon_price_per_t: float = 0.0
    emissions_limit_t_per_mwh: float | None = None
    emissions_limit_scope: str = "expected"
    time_limit_seconds: float = 300.0
    solver_method: str = "highs"

    def __post_init__(self) -> None:
        _nonnegative("carbon_price_per_t", self.carbon_price_per_t)
        if self.emissions_limit_t_per_mwh is not None:
            _nonnegative("emissions_limit_t_per_mwh", self.emissions_limit_t_per_mwh)
        if self.emissions_limit_scope not in ("expected", "per_period"):
            raise ValueError("emissions_limit_scope must be 'expected' or 'per_period'")
        if not np.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds must be positive and finite")
        if self.solver_method not in ("highs", "highs-ipm", "highs-ds"):
            raise ValueError("solver_method must be highs, highs-ipm or highs-ds")
