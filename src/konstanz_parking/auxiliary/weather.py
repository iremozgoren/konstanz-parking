"""DWD hourly observations for station 02712 (Konstanz).

``MESS_DATUM`` is UTC (DWD hourly data since 2000) and marks the *end* of the measuring hour for
sums (precipitation ``R1``, sunshine ``SD_SO``). Temperature, humidity and wind are values at that
time. ``-999`` = missing. Historical and recent ("akt") files overlap; historical (quality
checked) wins.

Sunshine (``SD_SO``) is only reported for hours ending 03-20 UTC. The other hours are night in
Konstanz all year round (earliest sunrise ~03:20 UTC, latest sunset ~19:35 UTC), so they are
set to 0 minutes rather than left missing.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

COLUMNS = {
    "TT_TU": "temp_c",
    "RF_TU": "rel_humidity",
    "R1": "precip_mm",
    "RS_IND": "precip_ind",
    "SD_SO": "sunshine_min",
    "F": "wind_ms",
}


def read_dwd_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.startswith("produkt_"))
        with z.open(name) as f:
            df = pd.read_csv(f, sep=";", skipinitialspace=True, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    ts = pd.to_datetime(df["MESS_DATUM"].str.slice(0, 10), format="%Y%m%d%H", utc=True)
    keep = [c for c in COLUMNS if c in df.columns]
    out = df[keep].apply(pd.to_numeric, errors="coerce").mask(lambda x: x <= -999)
    out.index = pd.DatetimeIndex(ts, name="hour_end_utc")
    return out.rename(columns=COLUMNS)


def load_weather(dwd_dir: Path) -> pd.DataFrame:
    """Hourly weather indexed by the end of the hour (UTC)."""
    products: dict[str, list[pd.DataFrame]] = {}
    for path in sorted(dwd_dir.glob("stundenwerte_*_02712_*.zip")):
        code = path.name.split("_")[1]
        df = read_dwd_zip(path)
        df["_hist"] = path.name.endswith("_hist.zip")
        products.setdefault(code, []).append(df)
    if not products:
        raise FileNotFoundError(f"no DWD files in {dwd_dir}; run `konstanz-parking fetch-aux`")
    merged = []
    for frames in products.values():
        df = pd.concat(frames).sort_values("_hist", ascending=False)  # historical first
        df = df[~df.index.duplicated(keep="first")].drop(columns="_hist").sort_index()
        merged.append(df)
    weather = pd.concat(merged, axis=1).sort_index()
    if "precip_ind" in weather:
        weather["precip_ind"] = weather["precip_ind"].astype("Int64")
    full = pd.date_range(weather.index.min(), weather.index.max(), freq="h", name="hour_end_utc")
    weather = weather.reindex(full)
    night = ~weather.index.hour.isin(range(3, 21))
    weather.loc[night, "sunshine_min"] = weather.loc[night, "sunshine_min"].fillna(0.0)
    return weather


def to_15min(weather: pd.DataFrame, grid_utc: pd.DatetimeIndex) -> pd.DataFrame:
    """Weather for each 15-min bin [t, t+15min): the hourly record whose hour contains the bin,
    i.e. the record ending at ``ceil(t + 1 min, 'h')``."""
    hour_end = (grid_utc + pd.Timedelta(minutes=1)).ceil("h")
    w = weather.reindex(hour_end)
    w.index = grid_utc
    return w
