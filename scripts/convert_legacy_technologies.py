#!/usr/bin/env python3
"""Derive the modern technology table from the recovered 2017 CSV inputs."""
from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "technology"
OUTPUT = ROOT / "config" / "technologies_2017.csv"
FIELDS = ("cf", "avail", "lcoe", "vom", "fuel.cost", "therm.effic", "co2")
ORDER = ("nuclear", "ccgt", "gas", "wind", "solar")
PROFILE = {"nuclear": "firm", "ccgt": "firm", "gas": "firm", "wind": "wind", "solar": "solar"}


def read_sources() -> dict[str, dict[str, float]]:
    values: dict[str, dict[str, float]] = {}
    for path in sorted(SOURCE.glob("input_*.csv")):
        with path.open(newline="") as handle:
            rows = csv.DictReader(handle)
            if rows.fieldnames is None or set(rows.fieldnames[1:]) != set(FIELDS):
                raise ValueError(f"{path}: unexpected technology columns")
            for row_number, row in enumerate(rows, start=2):
                name = (row[rows.fieldnames[0]] or "").strip()
                if not name:
                    raise ValueError(f"{path}:{row_number}: blank technology name")
                current = {field: float(row[field]) for field in FIELDS}
                if name in values:
                    for field in FIELDS:
                        if current[field] != values[name][field]:
                            raise ValueError(f"inconsistent duplicate parameters for {name}.{field}: {path}")
                else:
                    values[name] = current
    missing = set(ORDER) - set(values)
    if missing:
        raise ValueError(f"missing recovered technology parameters: {sorted(missing)}")
    return values


def main() -> None:
    source = read_sources()
    rows = []
    for name in ORDER:
        values = source[name]
        variable = values["fuel.cost"] * 3.6 / values["therm.effic"] + values["vom"]
        fixed = (values["lcoe"] - variable) * values["cf"] * 8760
        if fixed < 0 or variable < 0:
            raise ValueError(f"derived cost is negative for {name}")
        rows.append({
            "name": name, "profile": PROFILE[name],
            "annual_fixed_cost_per_mw": repr(fixed),
            "variable_cost_per_mwh": repr(variable),
            "co2_t_per_mwh": repr(values["co2"]),
            "availability": repr(values["avail"]),
            "min_capacity_mw": "0", "max_capacity_mw": "",
        })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "name", "profile", "annual_fixed_cost_per_mw", "variable_cost_per_mwh",
            "co2_t_per_mwh", "availability", "min_capacity_mw", "max_capacity_mw"))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Derived {OUTPUT} from {len(list(SOURCE.glob('input_*.csv')))} recovered input tables")


if __name__ == "__main__":
    main()
