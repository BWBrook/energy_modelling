import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tomllib
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy
import scipy

from energymod import __version__
from energymod.data import read_technologies, read_trace
from energymod.model import solve
from energymod.reporting import write_results
from energymod.schema import PlanningOptions, Storage
from energymod.validation import audit_solution


def load_config(path: Path):
    path = path.resolve()
    config = tomllib.loads(path.read_text())
    unknown = set(config) - {"name", "description", "inputs", "planning", "storage"}
    if unknown:
        raise ValueError(f"Unknown configuration sections: {sorted(unknown)}")
    inputs = config["inputs"]
    unknown = set(inputs) - {"technologies", "trace", "trace_format", "technology_names", "periods"}
    if unknown:
        raise ValueError(f"Unknown input options: {sorted(unknown)}")
    technology_path = (path.parent / inputs["technologies"]).resolve()
    trace_path = (path.parent / inputs["trace"]).resolve()
    technologies = read_technologies(technology_path)
    if "technology_names" in inputs:
        selected = inputs["technology_names"]
        if not selected or len(set(selected)) != len(selected):
            raise ValueError("technology_names must be a nonempty list of unique names")
        lookup = {t.name: t for t in technologies}
        if set(selected) - set(lookup):
            raise ValueError(f"Unknown technologies: {sorted(set(selected) - set(lookup))}")
        technologies = [lookup[name] for name in selected]
    trace = read_trace(trace_path, format=inputs["trace_format"], periods=inputs.get("periods"))
    options = PlanningOptions(**config.get("planning", {}))
    storage = Storage(**config["storage"]) if "storage" in config else None
    return config, trace, technologies, options, storage, (path, technology_path, trace_path)


def _provenance(paths: tuple[Path, ...], config: dict) -> dict:
    root = Path(__file__).resolve().parents[2]
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                              capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                           capture_output=True, text=True)
    code = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(__file__).parent.glob("*.py"))}
    return {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "project_version": __version__, "python": platform.python_version(),
        "numpy": numpy.__version__, "scipy": scipy.__version__,
        "git_commit": revision.stdout.strip() if revision.returncode == 0 else None,
        "git_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
        "source_sha256": code,
        "inputs": [{"filename": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                   for p in paths],
        "configuration": config,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chronological NEM capacity planning")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("solve", "check-inputs"):
        child = sub.add_parser(command)
        child.add_argument("--config", type=Path, required=True)
        if command == "solve":
            child.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    folder = None
    created = False
    try:
        config, trace, technologies, options, storage, paths = load_config(args.config)
        if args.command == "check-inputs":
            print(json.dumps({"trace": trace.metadata, "technologies": [asdict(t) for t in technologies],
                              "planning": asdict(options), "storage": None if storage is None else asdict(storage)},
                             indent=2, allow_nan=False))
            return 0
        folder = args.output
        folder.mkdir(parents=True, exist_ok=False)
        created = True
        provenance = _provenance(paths, config)
        (folder / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        solution = solve(trace, technologies, options, storage)
        audit = audit_solution(trace, technologies, solution, options, storage)
        write_results(folder, trace, technologies, solution, audit, options, storage, provenance)
        print(f"{config['name']}: optimal and independently checked")
        print(f"Expected annual system cost: {audit['annual_total_cost']:,.2f}")
        print(f"Cost per MWh demand: {audit['cost_per_mwh_demand']:.4f}")
        print(f"Emissions: {audit['emissions_t_per_mwh_demand']:.6f} tCO2/MWh demand")
        print(f"Results: {folder}")
        for warning in audit["warnings"]:
            print(f"Warning: {warning}", file=sys.stderr)
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        if created and (folder / "provenance.json").exists() and not (folder / "summary.json").exists():
            (folder / "failure.json").write_text(json.dumps({"status": "failed", "error": str(exc)}, indent=2) + "\n")
        print(f"energymod: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
