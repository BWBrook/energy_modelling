"""Plot the tightest day in the matched-weather dispatch-demand replay."""

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from energymod.data import read_technologies


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results/modern_weather_replay"
DAY = "2025-06-26"


def day_series():
    trace = ROOT / "data/traces/modern_nem/canonical/dispatch.csv"
    with trace.open(newline="") as stream:
        rows = [r for r in csv.DictReader(stream) if r["timestamp"].startswith(DAY)]
    if [r["timestamp"] for r in rows] != [f"{DAY}T{h:02}:00:00+10:00" for h in range(24)]:
        raise ValueError(f"Expected 24 hourly AEST intervals for {DAY}")
    demand = np.array([float(r["demand_mw"]) for r in rows]) / 1000
    multiplier = json.loads((RESULTS / "provenance.json").read_text())["old_mean_multiplier"]
    profiles = {name: np.array([float(r[name]) for r in rows]) for name in ("wind", "solar")}
    profiles["firm"] = np.ones(24)
    techs = read_technologies(ROOT / "config/technologies_2017.csv")
    with (ROOT / "results/weather_test_2017/fleets.csv").open(newline="") as stream:
        fleets = {r["design_year"]: r for r in csv.DictReader(stream)}
    power = {}
    for fleet in ("2003-2004", "joint"):
        power[fleet] = sum(float(fleets[fleet][t.name + "_mw"]) * t.availability * profiles[t.profile]
                           for t in techs) / 1000
    return demand, multiplier, power


def main():
    demand, multiplier, power = day_series()
    scaled = demand * multiplier
    colors = {"2003-2004": "#007b8c", "joint": "#b6510c"}
    labels = {"2003-2004": "2003–04 fleet", "joint": "eight-year fleet"}
    ink = "#223243"
    fig, (day, evening) = plt.subplots(
        1, 2, figsize=(10.2, 4.6), gridspec_kw={"width_ratios": [2.25, 1]},
    )
    fig.subplots_adjust(left=0.08, right=0.985, bottom=0.15, top=0.68, wspace=0.28)
    fig.suptitle("NEM fleet replay on 26 June 2025", x=0.08, y=0.98, ha="left",
                 fontsize=19, fontweight="bold", color=ink)
    edges = np.arange(25)
    day.axvspan(17, 20, facecolor="#e0e5ea", alpha=0.65, zorder=0)
    day.stairs(demand, edges, baseline=None, color="#454b56", linewidth=2,
               label="Reported dispatch demand")
    day.stairs(scaled, edges, baseline=None, color="#794280", linewidth=2.4,
               label=f"Demand scaled to 2017 model mean (×{multiplier:.3f})", zorder=4)
    for fleet, series in power.items():
        day.stairs(series, edges, baseline=None, color=colors[fleet], linewidth=2,
                   linestyle="--" if fleet == "joint" else "-",
                   label=f"Available power, {labels[fleet]}")
    day.legend(loc="lower left", bbox_to_anchor=(-0.012, 1.14), ncols=2, frameon=False,
               fontsize=9.5, columnspacing=2, handlelength=2.4, borderaxespad=0)
    day.set_title("Hourly averages", loc="left", fontsize=12, fontweight="bold", color=ink)
    day.set_ylabel("Power (GW)")
    day.set_xlim(0, 24)
    day.set_xticks(range(0, 25, 4), [f"{h:02}:00" for h in range(0, 25, 4)])
    day.set_xlabel("Hour (AEST)")
    hours = np.array([17, 18, 19])
    for fleet, offset in zip(power, (-0.2, 0.2)):
        deficits = np.maximum(0, scaled[hours] - power[fleet][hours])
        bars = evening.bar(hours + offset, deficits, width=0.355, color=colors[fleet], zorder=2)
        evening.bar_label(bars, fmt="%.2f", padding=3, fontsize=10, color=ink)
    evening.set_title("Shortfall at scaled demand", loc="left", fontsize=12,
                      fontweight="bold", color=ink)
    evening.set_xticks(hours, [f"{h}:00" for h in hours])
    evening.set_xlabel("Hour beginning (AEST)")
    evening.set_ylabel("Shortfall (GW)")
    evening.margins(y=0.15)
    for ax in (day, evening):
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color("#88929b")
        ax.tick_params(length=3, colors=ink)
        ax.grid(axis="y", color="#d8dee3", linewidth=0.7)
        ax.set_axisbelow(True)
    fig.savefig(RESULTS / "worst_day.png", dpi=180, bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)


if __name__ == "__main__":
    main()
