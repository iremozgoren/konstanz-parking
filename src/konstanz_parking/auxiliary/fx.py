"""ECB euro reference rate, Swiss francs per euro (``EXR.D.CHF.EUR.SP00.A``).

The rate for day *d* is fixed at 14:15 CET and published around 16:00 CET on TARGET business
days. A 15-minute bin therefore uses the latest rate published *before* it: from 16:00 local on
day *d*, the rate of *d*; before that, the previous business day's rate. Weekends and TARGET
holidays carry the last rate forward. No look-ahead.

Lower CHF per EUR = stronger franc = cheaper shopping in Germany for Swiss residents.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

TZ = "Europe/Berlin"
PUBLICATION_HOUR = 16


def load_fx(path: Path) -> pd.Series:
    df = pd.read_csv(path, usecols=["TIME_PERIOD", "OBS_VALUE"])
    df = df.dropna(subset=["OBS_VALUE"])
    s = pd.Series(
        df["OBS_VALUE"].astype(float).to_numpy(),
        index=pd.to_datetime(df["TIME_PERIOD"]),
        name="chf_per_eur",
    ).sort_index()
    return s


def to_15min(fx: pd.Series, grid_utc: pd.DatetimeIndex) -> pd.Series:
    published = (fx.index + pd.Timedelta(hours=PUBLICATION_HOUR)).tz_localize(TZ).tz_convert("UTC")
    pub = pd.DataFrame({"published_utc": published, "chf_per_eur": fx.to_numpy()})
    grid = pd.DataFrame({"ts_utc": grid_utc}).reset_index()
    m = pd.merge_asof(
        grid.sort_values("ts_utc"),
        pub.sort_values("published_utc"),
        left_on="ts_utc",
        right_on="published_utc",
        direction="backward",
    ).sort_values("index")
    return pd.Series(m["chf_per_eur"].to_numpy(), index=grid_utc, name="chf_per_eur")
