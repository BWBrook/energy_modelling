from pathlib import Path
import runpy

import numpy as np
import pytest

from energymod.schema import Technology, TraceData


replay = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/weather_replay.py"))["replay"]


def test_frozen_dispatch_costs_and_events_across_removed_leap_day():
    durations = np.array([1., .5, .5, 1.])
    trace = TraceData(
        np.array([2., 6., 8., 7.]), {"firm": np.ones(4), "wind": np.full(4, .5),
                                     "solar": np.zeros(4)}, durations, durations * 2920,
        ("year",) * 4, ("2004-02-28T22:00", "2004-02-28T23:00",
                        "2004-02-28T23:30", "2004-03-01T00:00"),
    )
    tech = [Technology("gas", "firm", 2, 4, 0, availability=.5),
            Technology("wind", "wind", 3, 1, 0)]
    metrics, events = replay(trace, tech, [6, 4])
    assert metrics["max_shortfall_mw"] == 3
    assert metrics["unserved_mwh"] == 4
    assert metrics["shortage_hours"] == 2
    assert metrics["annual_cost"] == pytest.approx(24 + (2 * 3 + 3 * 2 * 4) * 2920)
    assert [e["duration_hours"] for e in events] == [1, 1]
    assert [e["unserved_mwh"] for e in events] == [2, 2]
    first = events[0]
    assert first["start"] == "2004-02-28T23:00"
    assert first["end_exclusive"] == "2004-02-29T00:00:00"
    assert first["peak_timestamp"] == "2004-02-28T23:30"
    assert (first["demand_mw"], first["wind_dispatch_mw"], first["firm_available_mw"]) == (8, 2, 3)
