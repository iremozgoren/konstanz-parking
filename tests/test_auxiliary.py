import io
import json
import zipfile

import pandas as pd

from konstanz_parking.auxiliary import covid, fx, holidays, weather


def test_extend_to_weekends():
    s, e = holidays.extend_to_weekends(pd.Timestamp("2018-02-12"), pd.Timestamp("2018-02-23"))
    assert (s, e) == (pd.Timestamp("2018-02-10"), pd.Timestamp("2018-02-25"))  # Sat..Sun
    s, e = holidays.extend_to_weekends(pd.Timestamp("2018-01-27"), pd.Timestamp("2018-02-04"))
    assert (s, e) == (pd.Timestamp("2018-01-27"), pd.Timestamp("2018-02-04"))  # already Sat..Sun


def test_school_flags_unknown_windows_and_missing_years():
    periods = pd.DataFrame(
        {
            "region": ["CH-ZH", "CH-ZH"],
            "kind": ["spring", "sport_unknown"],
            "start": pd.to_datetime(["2017-04-15", "2017-02-01"]),
            "end": pd.to_datetime(["2017-04-30", "2017-02-28"]),
        }
    )
    dates = pd.date_range("2016-12-30", "2017-05-02", freq="D")
    f = holidays.school_flags(periods, dates)["ch_zh_school_holiday"]
    assert f["2017-04-20"] is True or f["2017-04-20"] == True  # noqa: E712
    assert f["2017-03-15"] == False  # noqa: E712
    assert pd.isna(f["2017-02-10"])  # explicitly unknown
    assert pd.isna(f["2016-12-30"])  # no ZH data for 2016 in this table


def test_manual_csv_is_well_formed():
    m = holidays.load_manual_periods()
    assert set(m["region"]) == {"CH-TG", "CH-ZH"}
    assert (m["end"] >= m["start"]).all()
    assert m["source"].notna().all()
    # Every year 2015-2019 has 5 periods per canton (ZH sport weeks 2016/2017 as unknown).
    for region in ("CH-TG", "CH-ZH"):
        years = m[(m["region"] == region) & (m["start"].dt.year <= 2019)]["start"].dt.year
        assert years.value_counts().sort_index().tolist() == [5] * 5


def _openholidays_dir(tmp_path):
    d = tmp_path / "oh"
    d.mkdir()
    for region in ("DE-BW", "CH-TG", "CH-ZH"):
        (d / f"school_{region}_2020.json").write_text("[]")
    zh = [
        {  # Volksschule: used
            "startDate": "2020-04-13",
            "endDate": "2020-04-25",
            "name": [{"text": "Spring holidays"}],
            "groups": [{"code": "CH-ZH-VS"}],
        },
        {  # vocational schools only: ignored
            "startDate": "2020-05-21",
            "endDate": "2020-05-23",
            "name": [{"text": "Ascension Bridge"}],
            "groups": [{"code": "CH-ZH-BS"}, {"code": "CH-ZH-MS"}],
        },
    ]
    (d / "school_CH-ZH_2020.json").write_text(json.dumps(zh))
    bw = [{"startDate": "2020-06-02", "endDate": "2020-06-13", "name": [{"text": "Pentecost"}]}]
    (d / "school_DE-BW_2020.json").write_text(json.dumps(bw))
    return d


def test_calendar_interactions(tmp_path):
    cal = holidays.calendar("2020-04-01", "2020-08-02", _openholidays_dir(tmp_path))
    # 2020-04-13 Easter Monday: holiday in BW and CH -> not a German shopping day.
    assert not cal.loc["2020-04-13", "de_shopping_day"]
    assert cal.loc["2020-04-13", "swiss_holiday_german_shopping_day"] == False  # noqa: E712
    # 2020-04-14 (Tue): ZH spring holiday, German shopping day.
    assert cal.loc["2020-04-14", "swiss_school_holiday_german_shopping_day"] == True  # noqa: E712
    # 2020-05-22: only the vocational-school bridge day -> not a ZH school holiday.
    assert cal.loc["2020-05-22", "ch_zh_school_holiday"] == False  # noqa: E712
    # 2020-08-01 (Sat): Swiss national day, German shops open.
    assert cal.loc["2020-08-01", "swiss_public_holiday_german_shopping_day"] == True  # noqa: E712
    # Sundays are never German shopping days.
    assert not cal.loc["2020-08-02", "de_shopping_day"]
    # BW school holiday (Tue 2020-06-02 .. Sat 06-13) is extended to Sunday 06-14 only:
    # the day before it starts is a Monday, so there is no adjacent weekend at the start.
    assert cal.loc["2020-06-14", "de_school_holiday"] == True  # noqa: E712
    assert cal.loc["2020-05-31", "de_school_holiday"] == False  # noqa: E712


def test_covid_phase_boundaries():
    dates = pd.to_datetime(
        [
            "2020-03-15",
            "2020-03-16",
            "2020-03-18",
            "2020-04-19",
            "2020-04-20",
            "2020-06-14",
            "2020-06-15",
            "2020-12-16",
        ]
    )
    p = covid.phases(pd.DatetimeIndex(dates))
    assert p["covid_phase"].astype(str).tolist() == [
        "pre_covid",
        "border_closed_shops_open",
        "lockdown",
        "lockdown",
        "shops_open_border_closed",
        "shops_open_border_closed",
        "border_reopened",
        "later_covid",
    ]
    assert p.loc["2020-04-19", "ch_shops_closed_covid"]


def test_fx_uses_rate_only_after_publication():
    rates = pd.Series([1.10, 1.20], index=pd.to_datetime(["2020-06-05", "2020-06-08"]))  # Fri, Mon
    grid = pd.DatetimeIndex(
        pd.to_datetime(
            ["2020-06-05 15:45", "2020-06-05 16:00", "2020-06-08 10:00", "2020-06-08 16:15"]
        )
        .tz_localize("Europe/Berlin")
        .tz_convert("UTC")
    )
    out = fx.to_15min(rates, grid)
    assert pd.isna(out.iloc[0])  # nothing published yet
    assert out.iloc[1:].tolist() == [1.10, 1.10, 1.20]  # Monday morning still uses Friday's rate


def _dwd_zip(path, header, rows):
    buf = io.StringIO()
    buf.write(header + "\n" + "\n".join(rows) + "\n")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("produkt_xx_stunde_02712.txt", buf.getvalue())


def test_weather_load_and_15min_mapping(tmp_path):
    d = tmp_path / "dwd"
    d.mkdir()
    _dwd_zip(
        d / "stundenwerte_TU_02712_20200101_20201231_hist.zip",
        "STATIONS_ID;MESS_DATUM;QN_9;TT_TU;RF_TU;eor",
        [
            "2712;2020060110;3;  20.0;  50.0;eor",
            "2712;2020060111;3;  21.0;-999;eor",
            "2712;2020060122;3;  15.0;  80.0;eor",
        ],
    )
    _dwd_zip(
        d / "stundenwerte_SD_02712_20200101_20201231_hist.zip",
        "STATIONS_ID;MESS_DATUM;QN_7;SD_SO;eor",
        ["2712;2020060110;3; 60.0;eor", "2712;2020060111;3; 30.0;eor"],
    )
    w = weather.load_weather(d)
    assert pd.isna(w.loc["2020-06-01 11:00+00:00", "rel_humidity"])  # -999 -> missing
    assert w.loc["2020-06-01 22:00+00:00", "sunshine_min"] == 0  # night: not reported -> 0
    grid = pd.DatetimeIndex(pd.to_datetime(["2020-06-01 10:00", "2020-06-01 10:45"], utc=True))
    m = weather.to_15min(w, grid)
    # Bins in 10:00-11:00 UTC get the record for the hour ending 11:00.
    assert m["temp_c"].tolist() == [21.0, 21.0]
    assert m["sunshine_min"].tolist() == [30.0, 30.0]


def test_16_may_easing_does_not_open_the_border_for_shopping():
    dates = pd.DatetimeIndex(
        pd.to_datetime(["2020-03-15", "2020-05-15", "2020-05-16", "2020-06-14", "2020-06-15"])
    )
    p = covid.phases(dates)
    assert p["shopping_tourism_allowed"].tolist() == [True, False, False, False, True]
    assert p["border_partial_easing"].tolist() == [False, False, True, True, False]
    # 16 May stays inside the key window.
    assert (p.loc["2020-05-16":"2020-06-14", "covid_phase"] == "shops_open_border_closed").all()
