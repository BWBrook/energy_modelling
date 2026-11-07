"""Strict readers for the canonical model inputs and recovered 2017 files."""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np

from .schema import Technology, TraceData


TECH_FIELDS = (
    "name", "profile", "annual_fixed_cost_per_mw", "variable_cost_per_mwh",
    "co2_t_per_mwh", "availability", "min_capacity_mw", "max_capacity_mw",
)
CANONICAL_TRACE_FIELDS = ("timestamp", "period", "duration_hours", "demand_mw", "wind", "solar")
LEGACY_TRACE_FIELDS = ("index", "day", "month", "time", "t.year", "d.nem", "w.mean", "s.mean")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _float(value: str, field: str, row: int) -> float:
    if value is None or value.strip() == "":
        raise ValueError(f"row {row}: {field} is blank")
    try:
        number = float(value)
    except ValueError as error:
        raise ValueError(f"row {row}: {field} is not numeric") from error
    if not np.isfinite(number):
        raise ValueError(f"row {row}: {field} is not finite")
    return number


def _integer(value: str, field: str, row: int) -> int:
    number = _float(value, field, row)
    if not np.isclose(number, round(number), rtol=0, atol=0):
        raise ValueError(f"row {row}: {field} must be an integer")
    return int(round(number))


def _rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: missing CSV header")
        if len(set(reader.fieldnames)) != len(reader.fieldnames) or any(not field for field in reader.fieldnames):
            raise ValueError(f"{path}: header names must be unique and nonempty")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"{path}: a row has the wrong number of fields")
    return list(reader.fieldnames), rows


def read_technologies(path: str | Path) -> list[Technology]:
    """Read the strict canonical technology table."""
    path = Path(path)
    fields, rows = _rows(path)
    required = set(TECH_FIELDS[:6])
    allowed = required | {"min_capacity_mw", "max_capacity_mw"}
    if set(fields) != allowed:
        raise ValueError(f"{path}: expected columns {sorted(allowed)}, got {fields}")
    result: list[Technology] = []
    names: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        name = row["name"].strip()
        profile = row["profile"].strip()
        if not name or not profile or name in names:
            raise ValueError(f"row {row_number}: technology names and profiles must be unique and nonempty")
        names.add(name)
        optional = {}
        for field in ("min_capacity_mw", "max_capacity_mw"):
            optional[field] = None if row[field].strip() == "" else _float(row[field], field, row_number)
        result.append(Technology(
            name=name, profile=profile,
            annual_fixed_cost_per_mw=_float(row["annual_fixed_cost_per_mw"], "annual_fixed_cost_per_mw", row_number),
            variable_cost_per_mwh=_float(row["variable_cost_per_mwh"], "variable_cost_per_mwh", row_number),
            co2_t_per_mwh=_float(row["co2_t_per_mwh"], "co2_t_per_mwh", row_number),
            availability=_float(row["availability"], "availability", row_number),
            min_capacity_mw=optional["min_capacity_mw"] or 0.0,
            max_capacity_mw=optional["max_capacity_mw"],
        ))
    if not result:
        raise ValueError(f"{path}: technology table is empty")
    return result


def _periods_and_weights(periods: list[str], duration: np.ndarray) -> np.ndarray:
    unique: list[str] = []
    for period in periods:
        if not unique or period != unique[-1]:
            if period in unique:
                raise ValueError("periods must be contiguous")
            unique.append(period)
    weights = np.zeros(len(periods), dtype=float)
    for period in unique:
        selected = np.array(periods) == period
        total_duration = duration[selected].sum()
        if total_duration <= 0:
            raise ValueError(f"period {period!r} has no positive duration")
        weights[selected] = duration[selected] * 8760.0 / (len(unique) * total_duration)
    return weights


def _select_periods(periods: list[str], requested: Iterable[str] | None) -> np.ndarray:
    if requested is None:
        return np.ones(len(periods), dtype=bool)
    selected = list(requested)
    if not selected or any(not period for period in selected) or len(set(selected)) != len(selected):
        raise ValueError("periods selection must be nonempty, unique and nonblank")
    available = set(periods)
    unknown = set(selected) - available
    if unknown:
        raise ValueError(f"unknown periods requested: {sorted(unknown)}")
    return np.array([period in selected for period in periods], dtype=bool)


def _trace_data(path: Path, demand: np.ndarray, profiles: dict[str, np.ndarray],
                duration: np.ndarray, periods: list[str], timestamps: list[str],
                format_name: str, metadata: dict[str, object]) -> TraceData:
    if len(demand) == 0:
        raise ValueError(f"{path}: trace is empty")
    if len(set(timestamps)) != len(timestamps):
        raise ValueError(f"{path}: timestamps are duplicated")
    parsed = [datetime.fromisoformat(item) for item in timestamps]
    if any(right <= left for left, right in zip(parsed, parsed[1:])):
        raise ValueError(f"{path}: timestamps are not strictly increasing")
    for index, (left, right) in enumerate(zip(parsed, parsed[1:])):
        if periods[index] != periods[index + 1]:
            continue
        expected = timedelta(hours=float(duration[index]))
        if format_name == "legacy_nem":
            if right - left not in (expected, timedelta(hours=25)):
                raise ValueError(f"{path}: timestamp gap at row {index + 2} disagrees with one-hour model interval")
        elif right - left != expected:
            raise ValueError(f"{path}: timestamp gap at row {index + 2} disagrees with duration_hours")
    weights = _periods_and_weights(periods, duration)
    metadata = dict(metadata)
    metadata.update({"source_sha256": _sha256(path), "trace_format": format_name,
                     "periods": tuple(dict.fromkeys(periods)), "hours": len(demand),
                     "coverage": f"{timestamps[0]} to {timestamps[-1]}"})
    return TraceData(demand, profiles, duration, weights, tuple(periods), tuple(timestamps), metadata)


def _read_canonical(path: Path, requested_periods: Iterable[str] | None) -> TraceData:
    fields, rows = _rows(path)
    if set(fields) != set(CANONICAL_TRACE_FIELDS) and not set(CANONICAL_TRACE_FIELDS).issubset(fields):
        raise ValueError(f"{path}: expected canonical columns {CANONICAL_TRACE_FIELDS}")
    if "firm" in fields:
        raise ValueError(f"{path}: firm is a reserved profile supplied by the loader")
    timestamps: list[str] = []
    periods: list[str] = []
    duration: list[float] = []
    demand: list[float] = []
    profiles: dict[str, list[float]] = {field: [] for field in fields if field not in {"timestamp", "period", "duration_hours", "demand_mw"}}
    for row_number, row in enumerate(rows, start=2):
        stamp = row["timestamp"].strip()
        try:
            datetime.fromisoformat(stamp)
        except ValueError as error:
            raise ValueError(f"row {row_number}: invalid timestamp") from error
        period = row["period"].strip()
        if not period:
            raise ValueError(f"row {row_number}: period is blank")
        timestamps.append(stamp)
        periods.append(period)
        duration.append(_float(row["duration_hours"], "duration_hours", row_number))
        demand.append(_float(row["demand_mw"], "demand_mw", row_number))
        for field in profiles:
            profiles[field].append(_float(row[field], field, row_number))
    keep = _select_periods(periods, requested_periods)
    periods = [period for period, selected in zip(periods, keep) if selected]
    timestamps = [stamp for stamp, selected in zip(timestamps, keep) if selected]
    duration = [value for value, selected in zip(duration, keep) if selected]
    demand = [value for value, selected in zip(demand, keep) if selected]
    profiles = {name: [value for value, selected in zip(values, keep) if selected]
                for name, values in profiles.items()}
    demand_array = np.array(demand)
    if np.any(demand_array < 0):
        raise ValueError(f"{path}: demand_mw must be nonnegative")
    profiles["firm"] = np.ones(len(demand_array), dtype=float)
    return _trace_data(path, demand_array, {k: np.array(v) for k, v in profiles.items()},
                       np.array(duration), periods, timestamps, "canonical",
                       {"standard_calendar": "as supplied", "demand_repeat_status": "unknown"})


def _legacy_datetime(row: dict[str, str], row_number: int) -> datetime:
    year = _integer(row["t.year"], "t.year", row_number)
    day = _integer(row["day"], "day", row_number)
    month = _integer(row["month"], "month", row_number)
    hour = _integer(row["time"], "time", row_number)
    try:
        return datetime(year, month, day, hour)
    except ValueError as error:
        raise ValueError(f"row {row_number}: invalid legacy date fields") from error


def _read_legacy(path: Path, requested_periods: Iterable[str] | None) -> TraceData:
    fields, rows = _rows(path)
    if not set(LEGACY_TRACE_FIELDS).issubset(fields):
        raise ValueError(f"{path}: expected legacy columns {LEGACY_TRACE_FIELDS}")
    dates: list[datetime] = []
    demand: list[float] = []
    wind: list[float] = []
    solar: list[float] = []
    for row_number, row in enumerate(rows, start=2):
        if _integer(row["index"], "index", row_number) != row_number - 1:
            raise ValueError(f"row {row_number}: legacy index is not consecutive")
        dates.append(_legacy_datetime(row, row_number))
        demand.append(_float(row["d.nem"], "d.nem", row_number))
        wind.append(_float(row["w.mean"], "w.mean", row_number))
        solar.append(_float(row["s.mean"], "s.mean", row_number))
    if not dates:
        raise ValueError(f"{path}: trace is empty")
    periods = [f"{date.year if date.month >= 7 else date.year - 1}-{date.year + 1 if date.month >= 7 else date.year}"
               for date in dates]
    keep = _select_periods(periods, requested_periods)
    selected_periods = [period for period, selected in zip(periods, keep) if selected]
    selected_dates = [date for date, selected in zip(dates, keep) if selected]
    selected_demand = [value for value, selected in zip(demand, keep) if selected]
    selected_wind = [value for value, selected in zip(wind, keep) if selected]
    selected_solar = [value for value, selected in zip(solar, keep) if selected]
    counts = {period: selected_periods.count(period) for period in dict.fromkeys(selected_periods)}
    if any(count != 8760 for count in counts.values()):
        raise ValueError(f"{path}: each legacy weather year must contain exactly 8760 rows; got {counts}")
    for period in counts:
        period_dates = [date for date, label in zip(selected_dates, selected_periods) if label == period]
        start_year = int(period.split("-", 1)[0])
        expected: list[datetime] = []
        current = datetime(start_year, 7, 1)
        end = datetime(start_year + 1, 7, 1)
        while current < end:
            if not (current.month == 2 and current.day == 29):
                expected.append(current)
            current += timedelta(hours=1)
        if period_dates != expected:
            raise ValueError(f"{path}: period {period} does not match its expected 8760-hour calendar")
    demand_array = np.array(selected_demand)
    for values, name in ((demand_array, "d.nem"), (np.array(selected_wind), "w.mean"), (np.array(selected_solar), "s.mean")):
        if np.any(values < 0) or (name != "d.nem" and np.any(values > 1)):
            raise ValueError(f"{path}: {name} is outside its allowed range")
    blocks = [demand_array[np.array(selected_periods) == period] for period in dict.fromkeys(selected_periods)]
    repeated = all(np.array_equal(blocks[0], block) for block in blocks[1:])
    stamps = [date.isoformat(timespec="minutes") for date in selected_dates]
    return _trace_data(path, demand_array, {"wind": np.array(selected_wind), "solar": np.array(selected_solar),
                                             "firm": np.ones(len(selected_dates))},
                       np.ones(len(selected_dates)), selected_periods, stamps, "legacy_nem",
                       {"standard_calendar": "8760-hour financial years; leap days removed",
                        "demand_repeat_status": "repeated across weather years" if repeated else "varies"})


def read_trace(path: str | Path, format: str = "canonical",
               periods: Iterable[str] | None = None) -> TraceData:
    """Read canonical or recovered 2017 NEM trace without coercion or filling."""
    path = Path(path)
    if format == "canonical":
        return _read_canonical(path, periods)
    if format == "legacy_nem":
        return _read_legacy(path, periods)
    raise ValueError("format must be exactly 'canonical' or 'legacy_nem'")
