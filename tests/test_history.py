import datetime as dt

import pandas as pd

from konstanz_parking.history.coverage import daily_coverage, expected_slots_per_day
from konstanz_parking.history.load import parse_dump_filename
from konstanz_parking.history.lots import EXCLUDED_DUMPS, lot_for_dump


def test_parse_dump_filename():
    assert parse_dump_filename("konstanzlago-2020.csv") == ("lago", 2020, False)
    assert parse_dump_filename("konstanzaltstadt-2015.backup-2015.csv") == ("altstadt", 2015, True)
    assert parse_dump_filename("konstanz$parkgetbezeichnung-2022.csv") == (
        "$parkgetbezeichnung",
        2022,
        False,
    )
    assert parse_dump_filename("README.txt") is None


def test_renamed_dumps_map_to_one_lot_and_artefacts_are_excluded():
    assert lot_for_dump("augustinerkarstadt") == lot_for_dump("augustiner") == "augustiner"
    assert lot_for_dump("amseerhein") == lot_for_dump("bodenseeforum") == "bodenseeforum"
    for name in EXCLUDED_DUMPS:
        assert lot_for_dump(name) is None


def test_expected_slots_handle_dst_days():
    exp = expected_slots_per_day(pd.Timestamp("2020-03-28"), pd.Timestamp("2020-03-30"))
    assert exp.tolist() == [288, 276, 288]  # 2020-03-29: spring forward, 23 h
    exp = expected_slots_per_day(pd.Timestamp("2020-10-25"), pd.Timestamp("2020-10-25"))
    assert exp.tolist() == [300]  # fall back, 25 h


def test_daily_coverage_usable_requires_slots_and_changing_values():
    # Local day 2020-06-01 = 2020-05-31 22:00 UTC .. 2020-06-01 22:00 UTC.
    ts = pd.date_range("2020-05-31 22:00", periods=288, freq="5min", tz="UTC")
    changing = pd.DataFrame({"lot_id": "a", "ts_utc": ts, "free": range(288)})
    constant = pd.DataFrame({"lot_id": "b", "ts_utc": ts, "free": 7})
    sparse = pd.DataFrame({"lot_id": "c", "ts_utc": ts[::2], "free": range(144)})
    d = daily_coverage(pd.concat([changing, constant, sparse], ignore_index=True))
    d = d[d["date"] == dt.date(2020, 6, 1)].set_index("lot_id")
    assert d.loc["a", "usable"]
    assert not d.loc["b", "usable"]  # frozen
    assert not d.loc["c", "usable"]  # only 50 % of slots
    assert d.loc["c", "share"] == 0.5
