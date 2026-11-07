"""Join weather, CHF/EUR, holidays and COVID phases onto the cleaned 15-minute grid.

Calendar features are joined by *local* date (Europe/Berlin): holidays are local days.
Weather and FX are joined by UTC time (see ``weather.to_15min`` / ``fx.to_15min``).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from konstanz_parking.auxiliary import covid, fx, holidays, weather

TZ = "Europe/Berlin"


def build(grid: pd.DataFrame, external: Path) -> pd.DataFrame:
    """``grid`` = ``parkendd_15min.parquet`` (lot_id, ts_utc, ts_local, free, occupancy, ...)."""
    g = grid.copy()
    times = pd.DatetimeIndex(g["ts_utc"].drop_duplicates().sort_values())

    w = weather.to_15min(weather.load_weather(external / "dwd"), times)
    rate = fx.to_15min(fx.load_fx(external / "ecb" / "ecb_chf_eur_daily.csv"), times)
    per_time = w.join(rate)
    per_time.index.name = "ts_utc"

    local = g["ts_utc"].dt.tz_convert(TZ)
    g["date"] = local.dt.tz_localize(None).dt.normalize()
    start = g["date"].min().strftime("%Y-%m-%d")
    end = g["date"].max().strftime("%Y-%m-%d")
    cal = holidays.calendar(start, end, external / "openholidays")
    cal = cal.join(covid.phases(cal.index))

    g["hour"] = local.dt.hour
    g["minute_of_day"] = local.dt.hour * 60 + local.dt.minute
    g["day_of_week"] = local.dt.day_of_week
    g["is_saturday"] = g["day_of_week"] == 5
    g["month"] = local.dt.month
    g["year"] = local.dt.year

    out = g.merge(per_time, left_on="ts_utc", right_index=True, how="left")
    out = out.merge(cal, left_on="date", right_index=True, how="left")
    return out
