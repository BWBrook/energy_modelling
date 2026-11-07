"""Plot a checked result bundle without loading the entire hourly output."""

import argparse
import csv
import gzip
import json
from itertools import islice
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hours", type=int, default=168)
    args = parser.parse_args()
    if args.hours <= 0:
        parser.error("--hours must be positive")
    summary = json.loads((args.run / "summary.json").read_text())
    with gzip.open(args.run / "dispatch.csv.gz", "rt") as stream:
        rows = list(islice(csv.DictReader(stream), args.hours))
    columns = {name: np.array([float(row[name]) for row in rows])
               for name in rows[0] if name not in ("timestamp", "period")}
    time = np.r_[0, np.cumsum(columns["duration_hours"])][:-1]
    generation = [name for name in columns if name.startswith("generation_")
                  and columns[name].max() > 1e-6]
    labels = [name.removeprefix("generation_").removesuffix("_mw") for name in generation]
    values = [columns[name] / 1000 for name in generation]
    if columns["discharge_mw"].max() > 1e-6:
        values.append(columns["discharge_mw"] / 1000)
        labels.append("storage discharge")
    storage = summary["storage_assumptions"] is not None
    fig, axes = plt.subplots(2 if storage else 1, 1, figsize=(11, 6 if storage else 4),
                             sharex=True, squeeze=False,
                             gridspec_kw={"height_ratios": [2, 1]} if storage else {})
    ax = axes[0, 0]
    ax.stackplot(time, values, labels=labels, alpha=0.8)
    ax.plot(time, columns["demand_mw"] / 1000, color="black", linewidth=1.7, label="demand")
    if columns["charge_mw"].max() > 1e-6:
        ax.plot(time, (columns["demand_mw"] + columns["charge_mw"]) / 1000,
                color="black", linewidth=1, linestyle="--", label="demand + charging")
    ax.set_ylabel("Power (GW)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.18), ncol=4, frameon=False)
    if storage:
        axes[1, 0].plot(time + columns["duration_hours"], columns["soc_end_mwh"] / 1000,
                        color="#6d3f9c", linewidth=1.8)
        axes[1, 0].set_ylabel("End-of-hour energy (GWh)")
    axes[-1, 0].set_xlabel("Model hour from first snapshot")
    for item in axes[:, 0]:
        item.spines[["top", "right"]].set_visible(False)
        item.grid(axis="y", alpha=0.18)
        item.set_xlim(time[0], time[-1] + columns["duration_hours"][-1])
    title = summary["provenance"]["configuration"]["name"].replace("_", " ")
    fig.suptitle(title, y=1.01, fontsize=13)
    fig.text(0.01, 0.005, "Development example; assumptions and residual checks are recorded in the result bundle.",
             fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.025, 1, 0.98))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=160, bbox_inches="tight")


if __name__ == "__main__":
    main()
