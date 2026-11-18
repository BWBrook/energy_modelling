"""Plot maximum hourly shortfall for an eight-year fixed-fleet replay."""

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Rectangle


def read_grid(path):
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    years = sorted({row["design_year"] for row in rows})
    if len(years) != 8 or set(years) != {row["weather_year"] for row in rows}:
        raise ValueError("Expected the same eight years on both axes")
    grid = np.full((len(years), len(years)), np.nan)
    for row in rows:
        i, j = years.index(row["design_year"]), years.index(row["weather_year"])
        if np.isfinite(grid[i, j]):
            raise ValueError(f"Duplicate design/weather combination: {years[i]}, {years[j]}")
        value = float(row["max_shortfall_mw"])
        if not np.isfinite(value) or value < 0:
            raise ValueError(f"Invalid shortfall in MW: {value}")
        grid[i, j] = value / 1000
    if np.isnan(grid).any():
        raise ValueError("Missing a design/weather combination")
    return years, grid


def cell_label(gw):
    if gw == 0:
        return "0"
    if gw < 0.01:
        return "<0.01"
    return f"{gw:.2f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pairs", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    years, grid = read_grid(args.pairs)
    labels = [f"{year[:4]}–{year[-2:]}" for year in years]
    cmap = LinearSegmentedColormap.from_list(
        "shortfall", ["#fff1cb", "#f6b46e", "#d56c43", "#983c44", "#521d45"]
    )
    norm = Normalize(vmin=0, vmax=grid.max() or 1)
    ink = "#202935"
    fig, ax = plt.subplots(figsize=(8.2, 7.1))
    fig.subplots_adjust(left=0.155, right=0.925, bottom=0.16, top=0.895)
    ax.set_facecolor("white")
    image = ax.imshow(np.ma.masked_equal(grid, 0), cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(range(8), labels, fontsize=9)
    ax.set_yticks(range(8), labels, fontsize=10)
    ax.set_xticks(np.arange(9) - 0.5, minor=True)
    ax.set_yticks(np.arange(9) - 0.5, minor=True)
    ax.grid(which="minor", color="#c6cbd1", linewidth=0.55)
    ax.tick_params(which="both", length=0, pad=7, labelcolor=ink)
    ax.set_xlabel("Weather year used for replay", labelpad=9, color=ink)
    ax.set_ylabel("Weather year used to design the fleet", labelpad=11, color=ink)
    for spine in ax.spines.values():
        spine.set_color("#c6cbd1")
        spine.set_linewidth(0.55)
    for (i, j), gw in np.ndenumerate(grid):
        r, g, b, _ = cmap(norm(gw))
        dark = 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.53
        color = "#ffffff" if dark else (ink if gw > 0 else "#697481")
        ax.text(j, i, cell_label(gw), ha="center", va="center", fontsize=10, color=color)
        if i == j:
            ax.add_patch(Rectangle((j - 0.475, i - 0.475), 0.95, 0.95, fill=False,
                                   edgecolor="#6d7f91", linewidth=1))
    fig.suptitle("Peak hourly shortfall (GW)", x=0.155, y=0.98, ha="left",
                 fontsize=18, fontweight="bold", color=ink)
    fig.text(0.155, 0.923, "NEM generation fleets under eight historical weather years",
             fontsize=10.5, color="#4b5866")
    fig.text(0.155, 0.045, "0 = demand met throughout the year. Outlined cells replay a fleet’s design year.",
             fontsize=9, color="#4b5866")
    if grid.max() > 0:
        bar = fig.colorbar(image, ax=ax, fraction=0.033, pad=0.026, aspect=35)
        bar.ax.tick_params(labelsize=8, length=3)
        bar.outline.set_visible(False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=180, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


if __name__ == "__main__":
    main()
