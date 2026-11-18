"""Frozen-fleet dispatch and shortage events for the generation-only weather test."""

from collections.abc import Sequence
from datetime import datetime, timedelta

import numpy as np

from energymod.schema import Technology, TraceData


SHORTFALL_TOLERANCE_MW = 1e-5


def replay(trace: TraceData, technologies: Sequence[Technology], capacity_mw):
    """Serve as much demand as possible, then minimise cost, in a single period."""
    if len(set(trace.periods)) != 1:
        raise ValueError("Replay requires a single operating period")
    capacities = np.asarray(capacity_mw, dtype=float)
    if (not technologies or capacities.shape != (len(technologies),)
            or not np.all(np.isfinite(capacities)) or np.any(capacities < 0)):
        raise ValueError("Capacities must be a finite nonnegative vector in technology order")

    profiles = np.array([t.profile for t in technologies])
    available = np.column_stack([capacities[i] * t.availability * trace.profiles[t.profile]
                                 for i, t in enumerate(technologies)])
    variable_rates = np.array([t.variable_cost_per_mwh for t in technologies])
    dispatch = np.zeros_like(available)
    residual = trace.demand_mw.copy()
    for i in np.argsort(variable_rates, kind="stable"):
        dispatch[:, i] = np.minimum(available[:, i], residual)
        residual -= dispatch[:, i]
    shortage = np.maximum(0., trace.demand_mw - available.sum(axis=1))
    if not np.allclose(dispatch.sum(axis=1) + shortage, trace.demand_mw, rtol=0., atol=1e-7):
        raise ValueError("Fixed-fleet dispatch and shortfall do not balance demand")
    shortage[shortage <= SHORTFALL_TOLERANCE_MW] = 0.

    indices = np.flatnonzero(shortage)
    events = []
    if indices.size:
        stamps = [datetime.fromisoformat(trace.timestamps[i]) for i in indices]
        ends = [stamp + timedelta(hours=float(trace.duration_hours[i]))
                for stamp, i in zip(stamps, indices)]
        breaks = [j for j in range(1, len(indices))
                  if indices[j] != indices[j-1] + 1 or stamps[j] != ends[j-1]]
        for group in np.split(np.arange(len(indices)), breaks):
            rows = indices[group]
            peak = rows[np.argmax(shortage[rows])]
            events.append({
                "start": trace.timestamps[rows[0]],
                "end_exclusive": ends[group[-1]].isoformat(),
                "duration_hours": float(trace.duration_hours[rows].sum()),
                "unserved_mwh": float(shortage[rows] @ trace.duration_hours[rows]),
                "peak_shortfall_mw": float(shortage[peak]),
                "peak_timestamp": trace.timestamps[peak],
                "demand_mw": float(trace.demand_mw[peak]),
                "wind_profile": float(trace.profiles["wind"][peak]),
                "solar_profile": float(trace.profiles["solar"][peak]),
                "wind_dispatch_mw": float(dispatch[peak, profiles == "wind"].sum()),
                "solar_dispatch_mw": float(dispatch[peak, profiles == "solar"].sum()),
                "firm_available_mw": float(available[peak, profiles == "firm"].sum()),
            })

    fixed_cost = float(capacities @ [t.annual_fixed_cost_per_mw for t in technologies])
    variable_cost = float((trace.annual_weights @ dispatch) @ variable_rates)
    metrics = {
        "max_shortfall_mw": float(shortage.max()),
        "unserved_mwh": float(shortage @ trace.duration_hours),
        "shortage_hours": float(trace.duration_hours[indices].sum()),
        "annual_fixed_cost": fixed_cost,
        "annual_variable_cost": variable_cost,
        "annual_cost": fixed_cost + variable_cost,
        "event_count": len(events),
    }
    return metrics, events
