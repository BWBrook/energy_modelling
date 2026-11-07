import json
from pathlib import Path

from energymod.cli import main


ROOT = Path(__file__).resolve().parents[1]


def test_demo_cli_produces_checked_bundle_and_preserves_existing_run(tmp_path):
    output = tmp_path / "run"
    args = ["solve", "--config", str(ROOT / "config/demo.toml"), "--output", str(output)]
    assert main(args) == 0
    summary = json.loads((output / "summary.json").read_text())
    assert summary["accounting"]["passed"]
    assert summary["status"] == "optimal_and_independently_checked"
    assert summary["accounting"]["max_hourly_balance_residual_mw"] < 1e-5
    assert (output / "capacity.csv").exists()
    assert (output / "periods.csv").exists()
    assert (output / "dispatch.csv.gz").exists()
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    assert main(args) == 2
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}


def test_illustrative_storage_is_built_and_balances(tmp_path):
    output = tmp_path / "storage"
    assert main(["solve", "--config", str(ROOT / "config/illustrative_storage.toml"),
                 "--output", str(output)]) == 0
    summary = json.loads((output / "summary.json").read_text())
    assert summary["storage_power_mw"] > 0
    assert summary["storage_energy_mwh"] > 0
    assert summary["accounting"]["annual_storage_loss_mwh"] > 0
    assert summary["accounting"]["max_simultaneous_storage_mw"] < 1e-5
    assert summary["accounting"]["annual_emissions_t"] < 1e-5
