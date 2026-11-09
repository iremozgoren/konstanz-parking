"""Daily (and 15-minute) analysis panels built from ``features_15min.parquet``.

Definitions follow ``reports/analysis_plan.md`` (pre-specified before any model was run).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HOURS = (10, 18)  # local bins 10:00-17:45
BINS_PER_DAY = (HOURS[1] - HOURS[0]) * 4
MIN_VALID_BINS = 24

GROUPS = {
    "lago": "lago",
    "altstadt": "centre",
    "augustiner": "centre",
    "doebele": "centre",
    "fischmarkt": "centre",
    "marktstaette": "centre",
    "benediktiner": "less_shopping",
    "bodenseeforum": "less_shopping",
    "seerheincenter": "other",
}
GROUP_ORDER = ["lago", "centre", "less_shopping"]

DAY_COLS = [
    "de_public_holiday",
    "de_school_holiday",
    "de_shopping_day",
    "ch_public_holiday",
    "ch_school_holiday",
    "ch_tg_public_holiday",
    "ch_zh_public_holiday",
    "ch_tg_school_holiday",
    "ch_zh_school_holiday",
    "swiss_holiday_german_shopping_day",
    "swiss_public_holiday_german_shopping_day",
    "swiss_school_holiday_german_shopping_day",
    "covid_phase",
    "chf_per_eur",
]
WEATHER = ["temp_c", "temp_c2", "precip_mm", "sunshine_min"]
CONTROLS = [*WEATHER, "de_school", "bridge_day"]


def load_bins(processed: Path) -> pd.DataFrame:
    """Daytime 15-min bins (10:00-17:45 local) with occupancy in percentage points."""
    cols = [
        "lot_id",
        "ts_local",
        "date",
        "hour",
        "day_of_week",
        "occupancy",
        "capacity_effective",
        "temp_c",
        "precip_mm",
        "sunshine_min",
        *DAY_COLS,
    ]
    df = pd.read_parquet(processed / "features_15min.parquet", columns=cols)
    df = df[(df["hour"] >= HOURS[0]) & (df["hour"] < HOURS[1])].copy()
    df["lot_id"] = df["lot_id"].astype(str)
    df["y"] = df["occupancy"] * 100
    return df


def bridge_days(dates: pd.DatetimeIndex, holiday: pd.Series) -> pd.Series:
    """Mon-Fri working day squeezed between a BW public holiday and a weekend."""
    hol = holiday.reindex(dates, fill_value=False).astype(bool)
    prev_hol = hol.shift(1, fill_value=False)
    next_hol = hol.shift(-1, fill_value=False)
    dow = dates.day_of_week
    nxt_sat = pd.Series(dow == 4, index=dates)  # Friday: next day is Saturday
    prv_sun = pd.Series(dow == 0, index=dates)  # Monday: previous day is Sunday
    return ~hol & ((prev_hol & nxt_sat) | (next_hol & prv_sun))


def daily(bins: pd.DataFrame) -> pd.DataFrame:
    """One row per car park and local date with outcome, controls and calendar flags."""
    g = bins.groupby(["lot_id", "date"], observed=True)
    out = g.agg(
        y=("y", "mean"),
        n_valid=("y", "count"),
        capacity=("capacity_effective", "first"),
        day_of_week=("day_of_week", "first"),
    ).reset_index()
    out["valid_day"] = out["n_valid"] >= MIN_VALID_BINS

    per_date = (
        bins.drop_duplicates(["date", "ts_local"])
        .groupby("date")
        .agg(
            temp_c=("temp_c", "mean"),
            precip_mm=("precip_mm", "mean"),
            sunshine_min=("sunshine_min", "mean"),
            **{c: (c, "first") for c in DAY_COLS},
        )
    )
    per_date["temp_c2"] = per_date["temp_c"] ** 2
    all_dates = pd.date_range(per_date.index.min(), per_date.index.max(), freq="D")
    per_date["bridge_day"] = bridge_days(all_dates, per_date["de_public_holiday"]).reindex(
        per_date.index
    )
    out = out.merge(per_date, left_on="date", right_index=True, how="left")

    out["group"] = out["lot_id"].map(GROUPS)
    out["year"] = out["date"].dt.year
    out["month"] = out["date"].dt.month
    out["ym"] = out["date"].dt.strftime("%Y-%m")
    iso = out["date"].dt.isocalendar()
    out["week"] = iso["year"].astype(str) + "-" + iso["week"].astype(str).str.zfill(2)
    out["is_saturday"] = out["day_of_week"] == 5
    out["de_school"] = out["de_school_holiday"].astype("Float64").fillna(0).astype(float)
    for c in ["bridge_day", "de_shopping_day", "de_public_holiday"]:
        out[c] = out[c].astype(bool)
    out["bridge_day"] = out["bridge_day"].astype(float)
    return out


def usable(d: pd.DataFrame) -> pd.DataFrame:
    """Valid shopping days with complete weather (the common analysis base)."""
    m = d["valid_day"] & d["de_shopping_day"] & d[WEATHER].notna().all(axis=1)
    return d[m].copy()


def doy_in(dates: pd.Series, start: str, end: str) -> pd.Series:
    """Calendar dates between ``start`` and ``end`` ("MM-DD", inclusive) in any year."""
    md = dates.dt.month * 100 + dates.dt.day
    a = int(start.replace("-", ""))
    b = int(end.replace("-", ""))
    return (md >= a) & (md <= b) if a <= b else (md >= a) | (md <= b)


def cars(effect_pp: float, d: pd.DataFrame) -> float:
    """Convert a pp effect into cars, using the summed effective capacity of the lots in ``d``."""
    cap = d.groupby("lot_id")["capacity"].median().sum()
    return float(effect_pp / 100 * cap) if np.isfinite(effect_pp) else float("nan")
