from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from energymod.data import read_technologies, read_trace


def write_trace(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "period", "duration_hours", "demand_mw", "wind", "solar"])
        writer.writerows(rows)


def test_canonical_loader_uses_duration_for_weights(tmp_path: Path) -> None:
    write_trace(tmp_path / "trace.csv", [
        ["2049-07-01T00:00", "a", "2", "10", "0.2", "0"],
        ["2049-07-01T02:00", "a", "1", "20", "0.5", "0.1"],
        ["2050-07-01T00:00", "b", "1", "30", "0.3", "0.2"],
    ])
    trace = read_trace(tmp_path / "trace.csv")
    assert np.allclose(trace.duration_hours, [2, 1, 1])
    assert np.allclose(trace.annual_weights, [2920, 1460, 4380])
    assert np.all(trace.profiles["firm"] == 1)
    assert trace.metadata["trace_format"] == "canonical"


def test_canonical_period_selection_filters_and_reweights(tmp_path: Path) -> None:
    write_trace(tmp_path / "trace.csv", [
        ["2049-07-01T00:00", "a", "1", "10", "0.2", "0"],
        ["2049-07-01T01:00", "a", "1", "20", "0.5", "0.1"],
        ["2050-07-01T00:00", "b", "1", "30", "0.3", "0.2"],
    ])
    trace = read_trace(tmp_path / "trace.csv", periods=["b"])
    assert trace.periods == ("b",)
    assert trace.demand_mw.tolist() == [30]
    assert trace.annual_weights.tolist() == [8760]
    for selection in ([], ["b", "b"], ["unknown"]):
        with pytest.raises(ValueError):
            read_trace(tmp_path / "trace.csv", periods=selection)


def test_canonical_firm_column_is_reserved(tmp_path: Path) -> None:
    path = tmp_path / "firm.csv"
    with path.open("w") as handle:
        handle.write("timestamp,period,duration_hours,demand_mw,wind,solar,firm\n")
        handle.write("2049-07-01T00:00,a,1,10,0.2,0,0\n")
    with pytest.raises(ValueError, match="reserved"):
        read_trace(path)


@pytest.mark.parametrize("bad", [
    [["2049-07-01T00:00", "a", "1", "10", "0.2", "0"],
     ["2049-07-01T00:00", "a", "1", "10", "0.2", "0"]],
    [["2049-07-01T00:00", "a", "2", "10", "0.2", "0"],
     ["2049-07-01T01:00", "a", "1", "10", "0.2", "0"]],
    [["2049-07-01T00:00", "a", "1", "10", "1.2", "0"]],
])
def test_canonical_loader_rejects_bad_rows(tmp_path: Path, bad: list[list[str]]) -> None:
    path = tmp_path / "bad.csv"
    write_trace(path, bad)
    with pytest.raises(ValueError):
        read_trace(path)


def test_canonical_loader_rejects_duplicate_headers_and_short_rows(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text("timestamp,period,period,duration_hours,demand_mw,wind,solar\n")
    with pytest.raises(ValueError, match="header"):
        read_trace(duplicate)
    short = tmp_path / "short.csv"
    short.write_text("timestamp,period,duration_hours,demand_mw,wind,solar\n2049-07-01T00:00,a,1,10,0.2\n")
    with pytest.raises(ValueError, match="fields"):
        read_trace(short)


def test_legacy_fractional_date_fields_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "legacy.csv"
    path.write_text("index,day,month,time,t.year,d.nem,w.mean,s.mean\n1.5,1,7,0,2003,10,0.2,0\n")
    with pytest.raises(ValueError, match="integer"):
        read_trace(path, format="legacy_nem")


def test_technology_loader_and_derived_parameters() -> None:
    technologies = read_technologies(Path(__file__).parents[1] / "config" / "technologies_2017.csv")
    assert {tech.name for tech in technologies} == {"nuclear", "ccgt", "gas", "wind", "solar"}
    nuclear = next(tech for tech in technologies if tech.name == "nuclear")
    assert nuclear.profile == "firm"
    assert nuclear.annual_fixed_cost_per_mw == pytest.approx(531377.4776470589)
    assert nuclear.variable_cost_per_mwh == pytest.approx(22.641176470588235)


@pytest.mark.skipif(not (Path(__file__).parents[1] / "data/traces/nem_trace2.csv").exists(),
                    reason="recovered raw data are intentionally absent in a public checkout")
def test_recovered_legacy_trace_facts() -> None:
    trace = read_trace(Path(__file__).parents[1] / "data/traces/nem_trace2.csv", format="legacy_nem")
    assert len(trace.demand_mw) == 70080
    assert len(set(trace.periods)) == 8
    assert trace.annual_weights.sum() == pytest.approx(8760)
    assert trace.metadata["demand_repeat_status"] == "repeated across weather years"
    assert trace.demand_mw.max() == pytest.approx(42830.0775)
