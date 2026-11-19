import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
import runpy
from zipfile import ZipFile

import pytest


reader = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/modern_demand.py"))
hourly_table = reader["hourly_table"]
REGIONS = reader["REGIONS"]
END = datetime(2023, 8, 1, tzinfo=timezone(timedelta(hours=10)))
START = END - timedelta(hours=1)


def archive(path, table, columns, rows):
    dataset, time_field, _, fields = reader["TABLES"][table]
    text = StringIO()
    writer = csv.writer(text)
    writer.writerow(("C", "NEMP.WORLD"))
    writer.writerow(("I", *dataset, "1", time_field, "REGIONID", *columns, *fields))
    for i, region, *values in reversed(rows):
        timestamp = START + timedelta(minutes=i)
        writer.writerow(("D", *dataset, "1", timestamp.strftime("%Y/%m/%d %H:%M:%S"), region, *values))
    writer.writerow(("C", "END OF REPORT", len(rows)))
    with ZipFile(path / f"{table}_{START:%Y%m}.zip", "w") as z:
        z.writestr("PUBLIC.csv", text.getvalue())


def test_dispatch_interval_end_regions_and_physical_intervention(tmp_path):
    rows = [(m, region, "1", "0", m, m + 1) for m in range(5, 61, 5) for region in REGIONS]
    rows.extend((60, region, "1", "1", 60, 61) for region in REGIONS if region != "NSW1")
    rows.extend([(60, "NSW1", "1", "1", 72, 73), (60, "NSWN", "1", "0", 900, 900),
                 (0, "NSW1", "1", "0", 900, 900)])
    table = "DISPATCHREGIONSUM"
    columns = ("RUNNO", "INTERVENTION")
    archive(tmp_path, table, columns, rows)
    assert list(hourly_table(tmp_path, table, START, END)) == [(START, (163.5, 168.5), 0, 0)]
    archive(tmp_path, table, columns, rows[1:])
    with pytest.raises(ValueError, match=r"missing TOTALDEMAND for NSW1 ending 2023-07-31 23:05"):
        list(hourly_table(tmp_path, table, START, END))
    archive(tmp_path, table, columns, rows + rows[:1])
    with pytest.raises(ValueError, match="duplicate"):
        list(hourly_table(tmp_path, table, START, END))
    rows.remove((60, "NSW1", "1", "1", 72, 73))
    archive(tmp_path, table, columns, rows)
    with pytest.raises(ValueError, match="missing region in physical intervention"):
        list(hourly_table(tmp_path, table, START, END))


def test_actuals_and_rooftop_selection(tmp_path):
    measured = [(m, region, m) for m in (30, 60) for region in REGIONS]
    archive(tmp_path, "DEMANDOPERATIONALACTUAL", (), measured)
    assert list(hourly_table(tmp_path, "DEMANDOPERATIONALACTUAL", START, END)) == [(START, (225,), 0, 0)]

    rows = [(m, region, "MEASUREMENT", "" if (m, region) == (30, "NSW1") else 1)
            for m in (30, 60) for region in REGIONS]
    rows += [(m, region, "SATELLITE", 3) for m in (30, 60) for region in REGIONS]
    table = "ROOFTOP_PV_ACTUAL"
    archive(tmp_path, table, ("TYPE",), rows)
    assert list(hourly_table(tmp_path, table, START, END)) == [(START, (6,), 1, 0)]
    rows.remove((30, "NSW1", "SATELLITE", 3))
    archive(tmp_path, table, ("TYPE",), rows)
    assert list(hourly_table(tmp_path, table, START, END)) == [(START, (None,), 0, 1)]
