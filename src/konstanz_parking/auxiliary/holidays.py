"""Daily holiday calendar for Baden-Württemberg (DE-BW) and the cantons Thurgau (CH-TG) and
Zürich (CH-ZH).

Public holidays: the ``holidays`` package.

School holidays:
- DE-BW: OpenHolidays API, all years.
- CH-TG / CH-ZH from 2020: OpenHolidays API. For Zürich only entries for the Volksschule
  (compulsory school; group ``*-VS``) or without a group are used. Entries for vocational and
  upper-secondary schools only (``*-BS``/``*-MS``) are ignored.
- CH-TG / CH-ZH 2015-2019 (and the ZH sport week 2020): ``ch_school_holidays_manual.csv``,
  transcribed from the EDK's national school holiday lists (see the ``source`` column).
- Zürich's sport week is set by each municipality. Where no canton-wide date exists (2016, 2017,
  2021, 2022), February is marked *unknown* (``<NA>``) rather than guessed.

Every school holiday period is extended to the adjacent weekend(s) (e.g. Mon-Fri -> Sat-Sun),
because sources differ in whether they list the weekends, and families travel on them.

German shops are closed on Sundays and BW public holidays. A Swiss holiday can only bring Swiss
shoppers to Konstanz on a *German shopping day* (Mon-Sat, not a BW public holiday); hence the
``swiss_*_german_shopping_day`` interaction features.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import holidays as pyholidays
import pandas as pd

PUBLIC = {"de": ("DE", "BW"), "ch_tg": ("CH", "TG"), "ch_zh": ("CH", "ZH")}
SCHOOL = {"de": "DE-BW", "ch_tg": "CH-TG", "ch_zh": "CH-ZH"}
OPENHOLIDAYS_FROM = {"DE-BW": 2015, "CH-TG": 2020, "CH-ZH": 2020}
MANUAL_CSV = "ch_school_holidays_manual.csv"


def public_holidays(dates: pd.DatetimeIndex) -> pd.DataFrame:
    years = sorted(set(dates.year))
    out = pd.DataFrame(index=dates)
    for key, (country, subdiv) in PUBLIC.items():
        h = pyholidays.country_holidays(country, subdiv=subdiv, years=years)
        names = pd.Series({pd.Timestamp(d): n for d, n in h.items()}, dtype=object)
        out[f"{key}_public_holiday_name"] = names.reindex(dates)
        out[f"{key}_public_holiday"] = out[f"{key}_public_holiday_name"].notna()
    return out


def load_manual_periods() -> pd.DataFrame:
    with resources.files("konstanz_parking.auxiliary").joinpath(MANUAL_CSV).open() as f:
        df = pd.read_csv(f, parse_dates=["start", "end"])
    return df.rename(columns={"canton": "region"})


def _use_openholidays_entry(entry: dict) -> bool:
    groups = entry.get("groups")
    return not groups or any(g["code"].endswith("-VS") for g in groups)


def load_openholidays_periods(directory: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(directory.glob("school_*_*.json")):
        _, region, year = path.stem.split("_")
        if int(year) < OPENHOLIDAYS_FROM[region]:
            continue
        for e in json.loads(path.read_text()):
            if not _use_openholidays_entry(e):
                continue
            rows.append(
                {
                    "region": region,
                    "kind": e["name"][0]["text"],
                    "start": pd.Timestamp(e["startDate"]),
                    "end": pd.Timestamp(e["endDate"]),
                    "source": "OpenHolidays API",
                    "note": "",
                    "year": int(year),
                }
            )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Periods spanning New Year appear in both years' responses.
    return df.drop_duplicates(["region", "start", "end"])


def school_periods(openholidays_dir: Path) -> pd.DataFrame:
    """All school holiday periods as published (before weekend extension)."""
    manual = load_manual_periods()
    oh = load_openholidays_periods(openholidays_dir)
    cols = ["region", "kind", "start", "end", "source", "note"]
    return pd.concat([manual[cols], oh[cols]], ignore_index=True).sort_values(["region", "start"])


def extend_to_weekends(start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    one = pd.Timedelta(days=1)
    while (start - one).day_of_week >= 5:
        start -= one
    while (end + one).day_of_week >= 5:
        end += one
    return start, end


def school_flags(periods: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Nullable boolean per region: True in a holiday, False outside, <NA> where unknown
    (explicitly unknown windows, or years without any data for that region)."""
    out = pd.DataFrame(index=dates)
    for key, region in SCHOOL.items():
        p = periods[periods["region"] == region]
        flag = pd.Series(False, index=dates, dtype="boolean")
        known = p[~p["kind"].str.endswith("_unknown")]
        for s, e in zip(known["start"], known["end"], strict=True):
            s2, e2 = extend_to_weekends(s, e)
            flag[(dates >= s2) & (dates <= e2)] = True
        years_with_data = set(known["start"].dt.year) | set(known["end"].dt.year)
        flag[~dates.year.isin(list(years_with_data))] = pd.NA
        for s, e in zip(
            p.loc[p["kind"].str.endswith("_unknown"), "start"],
            p.loc[p["kind"].str.endswith("_unknown"), "end"],
            strict=True,
        ):
            in_window = (dates >= s) & (dates <= e)
            flag[in_window & ~flag.fillna(False)] = pd.NA
        out[f"{key}_school_holiday"] = flag
    return out


def calendar(start: str, end: str, openholidays_dir: Path) -> pd.DataFrame:
    """Daily calendar (local dates) with holiday and shopping-day features."""
    dates = pd.date_range(start, end, freq="D", name="date")
    cal = public_holidays(dates).join(school_flags(school_periods(openholidays_dir), dates))
    dow = dates.day_of_week
    cal["de_shopping_day"] = (dow <= 5) & ~cal["de_public_holiday"]
    cal["ch_public_holiday"] = cal["ch_tg_public_holiday"] | cal["ch_zh_public_holiday"]
    cal["ch_public_holiday_name"] = cal["ch_tg_public_holiday_name"].fillna(
        cal["ch_zh_public_holiday_name"]
    )
    # Kleene logic: True | <NA> = True, False | <NA> = <NA>.
    cal["ch_school_holiday"] = cal["ch_tg_school_holiday"] | cal["ch_zh_school_holiday"]
    shop = cal["de_shopping_day"].astype("boolean")
    ch_public = cal["ch_public_holiday"].astype("boolean")
    cal["swiss_public_holiday_german_shopping_day"] = ch_public & shop
    cal["swiss_school_holiday_german_shopping_day"] = cal["ch_school_holiday"] & shop
    cal["swiss_holiday_german_shopping_day"] = (ch_public | cal["ch_school_holiday"]) & shop
    return cal.drop(columns=["ch_tg_public_holiday_name", "ch_zh_public_holiday_name"])
