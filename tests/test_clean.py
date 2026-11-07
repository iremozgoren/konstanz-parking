import pandas as pd
import pytest

from konstanz_parking.history.clean import clean, daytime_overlap_hours, to_grid


def readings(lot, start_local, values, step="5min", source="f.csv", backup=False):
    """Synthetic raw rows; ``start_local`` is Europe/Berlin wall time."""
    ts = pd.date_range(start_local, periods=len(values), freq=step, tz="Europe/Berlin")
    return pd.DataFrame(
        {
            "lot_id": lot,
            "dump_name": lot,
            "source_file": source,
            "is_backup": backup,
            "file_row": range(len(values)),
            "ts_utc": ts.tz_convert("UTC"),
            "free": pd.array(values, dtype="Int64"),
        }
    )


def wiggle(n, base=100):
    return [base + (i % 7) for i in range(n)]


def run(*frames):
    df, stats = clean(pd.concat(frames, ignore_index=True))
    return df, stats


def test_daytime_overlap_hours_including_dst_day():
    s = pd.Series(pd.to_datetime(["2020-03-29 05:00", "2020-06-01 18:00"]).tz_localize("UTC"))
    e = pd.Series(pd.to_datetime(["2020-03-29 20:00", "2020-06-02 08:00"]).tz_localize("UTC"))
    # 2020-03-29 is a 23 h day; 05:00 UTC = 07:00 CEST, 20:00 UTC = 22:00 CEST -> 09-19 = 10 h.
    # 2020-06-01 18:00 UTC = 20:00 CEST until 10:00 CEST next day -> 1 h (09-10).
    assert daytime_overlap_hours(s, e).tolist() == pytest.approx([10.0, 1.0])


def test_exact_and_conflicting_duplicates():
    a = readings("lago", "2020-06-01 10:00", wiggle(50))
    dup = a.iloc[[3]].copy()
    conflict = a.iloc[[5]].copy()
    conflict["free"] = pd.array([999], dtype="Int64")
    conflict["file_row"] = 1000
    df, stats = run(a, dup, conflict)
    assert stats.exact_duplicates == 1
    assert stats.conflicting_duplicates == 1
    assert len(df) == 50
    kept = df.loc[df["dup_conflict"], "free"].tolist()
    assert kept == [a.iloc[5]["free"]]  # first occurrence in file order wins


def test_frozen_runs_and_gaps():
    # Constant 13 h overnight+morning -> stuck_long.
    frozen = readings("lago", "2020-06-01 20:00", [500] * (13 * 12))
    # Constant 4 h at midday on another day -> stuck_day; 2 h constant -> fine.
    day4 = readings("lago", "2020-06-03 11:00", [400] * 48)
    day2 = readings("lago", "2020-06-04 11:00", [300] * 24)
    ok = readings("lago", "2020-06-05 08:00", wiggle(100))
    df, _ = run(frozen, day4, day2, ok)
    d = df.set_index("ts_local")
    assert d.loc["2020-06-02 06:00":"2020-06-02 08:00", "stuck_long"].all()
    assert d.loc["2020-06-03 12:00":"2020-06-03 13:00", "stuck_day"].all()
    assert not d.loc["2020-06-04", ["stuck_day", "stuck_long"]].any().any()
    assert d.loc["2020-06-05", "valid"].all()


def test_gap_breaks_runs():
    # Same value before and after a 2-day gap: two short runs, not one frozen run.
    a = readings("lago", "2020-06-01 21:00", [700] * 12)
    b = readings("lago", "2020-06-03 21:00", [700] * 12)
    df, _ = run(a, b, readings("lago", "2020-06-05 10:00", wiggle(20)))
    assert not df["stuck_long"].any()
    assert df["gap_before"].sum() == 2


def test_zero_at_night_is_closed_but_zero_on_saturday_midday_is_full():
    night = readings("lago", "2020-06-05 23:00", [0] * 6 * 12)  # Fri 23:00 - Sat 05:00
    full = readings("lago", "2020-06-06 11:00", [0] * 3 * 12)  # Sat 11:00 - 14:00
    rest = readings("lago", "2020-06-07 10:00", wiggle(50))
    df, _ = run(night, full, rest)
    d = df.set_index("ts_local")
    assert d.loc["2020-06-06 01:00":"2020-06-06 04:00", "zero_closed"].all()
    sat = d.loc["2020-06-06 11:00":"2020-06-06 13:30"]
    assert sat["valid"].all() and (sat["occupancy"] == 1).all()


def test_negative_and_hard_limit():
    vals = wiggle(60, base=200)
    vals[10] = -5
    vals[20] = 1410  # Seerheincenter official capacity 312 -> hard limit 374
    df, _ = run(readings("seerheincenter", "2020-06-01 10:00", vals))
    assert df.loc[df["free"] == -5, "negative"].all()
    assert df.loc[df["free"] == 1410, "implausible_high"].all()
    assert df["capacity_effective"].max() < 300  # not inflated by the bogus reading
    assert df["valid"].sum() == 58


def test_backup_rows_only_used_before_main_file_starts():
    backup = readings("altstadt", "2015-07-01 10:00", wiggle(100), source="b.csv", backup=True)
    main = readings("altstadt", "2015-07-01 14:00", wiggle(60), source="m.csv")
    df, stats = run(backup, main)
    assert stats.backup_superseded == 52  # backup rows from 14:00 on
    assert df["from_backup"].sum() == 48
    assert stats.backup_agreement.iloc[0]["pairs"] == 52


def test_grid_interpolates_only_short_gaps():
    vals = wiggle(12 * 6)
    a = readings("lago", "2020-06-01 10:00", vals)
    local = a["ts_utc"].dt.tz_convert("Europe/Berlin")
    short_gap = local.between("2020-06-01 11:00", "2020-06-01 11:25")  # 2 empty bins
    long_gap = local.between("2020-06-01 13:30", "2020-06-01 14:55")  # 6 empty bins
    a = a[~short_gap & ~long_gap]
    df, _ = run(a)
    grid = to_grid(df).set_index("ts_local")
    assert grid.loc["2020-06-01 11:00", "interpolated"]
    assert grid.loc["2020-06-01 11:15", "interpolated"]
    assert grid.loc["2020-06-01 13:30":"2020-06-01 14:45", "free"].isna().all()
    assert not grid.loc["2020-06-01 13:30":"2020-06-01 14:45", "interpolated"].any()
    assert not grid["free"].loc["2020-06-01 10:00":"2020-06-01 10:45"].isna().any()


def test_zero_dip_between_high_values_is_a_glitch_but_gradual_fill_is_not():
    # LAGO-like morning reset: 910 -> 0 (15 min) -> 909.
    glitch = readings(
        "lago", "2020-06-01 06:30", [910] * 6 + [0] * 3 + [909, 905, 900] + wiggle(30, 880)
    )
    # Gradual fill-up to 0 on Saturday midday, then slowly emptying.
    fill = list(range(60, 0, -5)) + [0] * 6 + list(range(5, 65, 5))
    full = readings("lago", "2020-06-06 10:00", fill)
    df, _ = run(glitch, full)
    d = df.set_index("ts_local")
    assert d.loc["2020-06-01 07:00":"2020-06-01 07:10", "zero_dip"].all()
    sat_zero = d.loc["2020-06-06"].query("free == 0")
    assert len(sat_zero) == 6 and sat_zero["valid"].all()
