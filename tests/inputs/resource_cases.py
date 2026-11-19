"""Exercise the optional AEMO reader with small synthetic MMSDM archives."""

import csv
from datetime import datetime
from io import StringIO
from pathlib import Path
import runpy
from zipfile import ZipFile

import numpy as np
import pytest


reader = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/modern_resources.py"))


def write_archive(path, rows):
    data = StringIO()
    writer = csv.writer(data)
    writer.writerow(["C", "TEST"])
    writer.writerow(["I", "DISPATCH", "LOAD", "1", "SETTLEMENTDATE", "DUID", "RUNNO",
                     "INTERVENTION", "AVAILABILITY", "UIGF"])
    for end, duid, flag, avail, uigf in rows:
        writer.writerow(["D", "DISPATCH", "LOAD", "1", f"2023/08/07 {end}:00", duid,
                         1, flag, avail, uigf])
    writer.writerow(["C", "END OF REPORT", len(rows)])
    with ZipFile(path, "w") as z:
        z.writestr("PUBLIC.csv", data.getvalue())


def test_field_transition_and_physical_run(tmp_path):
    path = tmp_path / "DISPATCHLOAD_202308.zip"
    rows = [("13:35", "WF1", 0, 9, ""), ("13:40", "WF1", 1, 20, 25),
            ("13:40", "WF1", 0, 7, 5), ("13:45", "WF1", 0, 18, 13),
            ("13:45", "WF1", 1, 15, ""), ("13:50", "WF1", 0, 33, "")]
    write_archive(path, rows)
    begin, mw = reader["read_month"](path, ["WF1"])
    first_start = np.datetime64(datetime(2023, 8, 7, 13, 30), "s")
    i = int((first_start - reader["START"]) / np.timedelta64(5, "m")) - begin
    np.testing.assert_equal(mw[i:i+4, 0], [9, 25, np.nan, np.nan])

    write_archive(path, rows + [("13:40", "WF2", 0, 8, 2)])
    with pytest.raises(ValueError, match="Missing physical run"):
        reader["read_month"](path, ["WF1", "WF2"])
    write_archive(path, rows + rows[:1])
    with pytest.raises(ValueError, match="Duplicate interval"):
        reader["read_month"](path, ["WF1"])
