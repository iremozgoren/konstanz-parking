"""Cleaning pipeline for the ParkenDD history.

Principles:
- The raw dumps are never modified. Output goes to ``data/processed/`` as Parquet.
- Rows are flagged, not deleted (except exact duplicates and backup rows superseded by the main
  file, which are counted). ``valid`` combines the flags that make a reading unusable.
- Timestamps stay in UTC (``ts_utc``); ``ts_local`` (Europe/Berlin) is added for analysis.

Flag rules (thresholds calibrated on the data, see the quality report):
- ``negative``: free < 0.
- ``stuck_long``: the same value for >= 12 h (sensor or scraper frozen, or outage).
- ``stuck_day``: the same non-zero value for >= 3 h *of daytime* (09-19 local). A busy car park
  does not stay exactly constant for three daytime hours.
- ``zero_closed``: a run of 0 lasting >= 1 h that is (almost) entirely outside daytime. Several car
  parks report 0 while closed at night: that is "no data", not "full".
  Zero runs *during* the day are kept: they cluster on Saturdays 10-13 h, i.e. the car park is full.
- ``zero_dip``: a run of 0 whose neighbouring readings (just before and after) are both above 20 %
  of effective capacity. Several car parks drop to 0 for ~15 min every morning at 07:00 local
  (and some at midnight), then return to ~900 free: a feed reset, not a full car park.
- ``implausible_high``: free > 1.05 x effective capacity, or free > 1.2 x the larger official
  capacity (ArcGIS / ParkenDD) where one is known. The hard limit is applied first so that bogus
  readings (e.g. Seerheincenter reporting 1410 free in mid-2020) cannot inflate the effective
  capacity, which is the 99.9th percentile of the remaining valid readings.
- ``censored_high`` (informational): Bodenseeforum never reports more than 500 free.
- ``above_official_capacity`` (informational): free > ArcGIS ``max_cap``.
Runs are broken at data gaps > 60 min, so a gap is never mistaken for a frozen sensor.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from konstanz_parking.history.lots import CAPACITY_BREAKS, LOTS_BY_ID

TZ = "Europe/Berlin"

GAP_MIN = 15  # a gap is > 15 min between consecutive readings (nominal interval 5 min)
RUN_BREAK_GAP_MIN = 60
DAY_START_H, DAY_END_H = 9, 19
STUCK_LONG_H = 12.0
STUCK_DAY_H = 3.0
ZERO_CLOSED_MIN_H = 1.0
ZERO_CLOSED_MAX_DAY_OVERLAP_H = 1.0
IMPLAUSIBLE_FACTOR = 1.05
ZERO_DIP_NEIGHBOUR_SHARE = 0.2
HARD_LIMIT_FACTOR = 1.2
EFFECTIVE_CAPACITY_QUANTILE = 0.999
CENSOR_AT = {"bodenseeforum": 500}

INVALID_FLAGS = [
    "negative",
    "stuck_long",
    "stuck_day",
    "zero_closed",
    "zero_dip",
    "implausible_high",
]
INFO_FLAGS = ["censored_high", "above_official_capacity", "dup_conflict", "from_backup"]


@dataclass
class CleaningStats:
    raw_rows: int = 0
    unparseable: int = 0
    backup_superseded: int = 0
    exact_duplicates: int = 0
    conflicting_duplicates: int = 0
    per_lot: pd.DataFrame = field(default_factory=pd.DataFrame)
    effective_capacity: dict[str, float] = field(default_factory=dict)
    backup_agreement: pd.DataFrame = field(default_factory=pd.DataFrame)


def _drop_superseded_backup(df: pd.DataFrame, stats: CleaningStats) -> pd.DataFrame:
    """Keep ``*.backup-2015`` rows only before the main 2015 file starts for that lot.

    During their overlap both scrapers sampled at different seconds, so the rows interleave.
    Their agreement is measured (nearest reading within 3 min) and reported.
    """
    main_start = df[~df["is_backup"]].groupby("lot_id", observed=True)["ts_utc"].min()
    starts = df["lot_id"].map(main_start)
    superseded = df["is_backup"] & (df["ts_utc"] >= starts)

    rows = []
    for lot, bk in df[superseded].groupby("lot_id", observed=True):
        main = df[(df["lot_id"] == lot) & ~df["is_backup"]][["ts_utc", "free"]].sort_values(
            "ts_utc"
        )
        m = pd.merge_asof(
            bk[["ts_utc", "free"]].sort_values("ts_utc"),
            main,
            on="ts_utc",
            direction="nearest",
            tolerance=pd.Timedelta("3min"),
            suffixes=("_backup", "_main"),
        ).dropna()
        diff = (m["free_backup"] - m["free_main"]).abs()
        rows.append(
            {
                "lot_id": lot,
                "pairs": len(m),
                "identical_pct": round(100 * (diff == 0).mean(), 1),
                "within_5_pct": round(100 * (diff <= 5).mean(), 1),
                "mean_abs_diff": round(float(diff.mean()), 2),
            }
        )
    stats.backup_agreement = pd.DataFrame(rows)
    stats.backup_superseded = int(superseded.sum())
    return df[~superseded]


def _deduplicate(df: pd.DataFrame, stats: CleaningStats) -> pd.DataFrame:
    df = df.sort_values(["lot_id", "ts_utc", "source_file", "file_row"], kind="stable")
    exact = df.duplicated(["lot_id", "ts_utc", "free"])
    stats.exact_duplicates = int(exact.sum())
    df = df[~exact]
    # Same timestamp, different value: keep the first occurrence in file order and flag it.
    conflict_dropped = df.duplicated(["lot_id", "ts_utc"], keep="first")
    stats.conflicting_duplicates = int(conflict_dropped.sum())
    has_conflict = df.duplicated(["lot_id", "ts_utc"], keep=False)
    df = df.assign(dup_conflict=has_conflict)[~conflict_dropped]
    return df.reset_index(drop=True)


def daytime_overlap_hours(start_utc: pd.Series, end_utc: pd.Series) -> np.ndarray:
    """Hours of overlap between each interval and the local daytime window (09-19 h).

    Computed per local calendar day, so DST days are handled by the time zone conversion.
    """
    out = np.zeros(len(start_utc))
    s_loc = start_utc.dt.tz_convert(TZ)
    e_loc = end_utc.dt.tz_convert(TZ)
    for i, (s, e) in enumerate(zip(s_loc, e_loc, strict=True)):
        total = 0.0
        day = s.normalize()
        while day <= e:
            # Build window bounds from the calendar date; 09:00 and 19:00 always exist (DST
            # switches happen at 02:00/03:00), so localising them is unambiguous.
            d = day.date()
            w0 = pd.Timestamp(d.year, d.month, d.day, DAY_START_H, tz=TZ)
            w1 = pd.Timestamp(d.year, d.month, d.day, DAY_END_H, tz=TZ)
            lo, hi = max(s, w0), min(e, w1)
            if hi > lo:
                total += (hi - lo).total_seconds() / 3600
            day = (day + pd.Timedelta(days=1, hours=2)).normalize()
        out[i] = total
    return out


def _runs(df: pd.DataFrame) -> pd.DataFrame:
    """Annotate constant-value runs: ``run_hours`` and ``run_day_overlap_h`` per row."""
    lot = df["lot_id"].astype(str)
    new_lot = lot != lot.shift()
    changed = df["free"] != df["free"].shift()
    gap = df["gap_before_min"] > RUN_BREAK_GAP_MIN
    run_id = (new_lot | changed | gap).cumsum()
    g = df.groupby(run_id)["ts_utc"]
    run_start, run_end = g.transform("min"), g.transform("max")
    run_hours = (run_end - run_start).dt.total_seconds() / 3600

    runs = pd.DataFrame({"run_id": run_id, "start": run_start, "end": run_end, "h": run_hours})
    runs = runs.drop_duplicates("run_id")
    long_runs = runs[runs["h"] >= ZERO_CLOSED_MIN_H]
    overlap = pd.Series(0.0, index=runs["run_id"].to_numpy())
    overlap.loc[long_runs["run_id"].to_numpy()] = daytime_overlap_hours(
        long_runs["start"], long_runs["end"]
    )
    # Values just before and just after each run (same lot only), for the zero-dip rule.
    pos = pd.Series(np.arange(len(df)), index=df.index)
    first_pos = pos.groupby(run_id).transform("min").to_numpy()
    last_pos = pos.groupby(run_id).transform("max").to_numpy()
    free = df["free"].to_numpy(dtype=float)
    lots = lot.to_numpy()
    prev_pos, next_pos = first_pos - 1, last_pos + 1
    prev_ok = (prev_pos >= 0) & (lots[np.clip(prev_pos, 0, None)] == lots)
    next_ok = (next_pos < len(df)) & (lots[np.clip(next_pos, None, len(df) - 1)] == lots)
    prev_free = np.where(prev_ok, free[np.clip(prev_pos, 0, None)], np.nan)
    next_free = np.where(next_ok, free[np.clip(next_pos, None, len(df) - 1)], np.nan)
    return df.assign(
        run_id=run_id,
        run_hours=run_hours,
        run_day_overlap_h=run_id.map(overlap).to_numpy(),
        run_prev_free=prev_free,
        run_next_free=next_free,
    )


def hard_limits() -> dict[str, float]:
    """1.2 x the larger official capacity per lot (lots without one are not limited)."""
    out = {}
    for lot_id, lot in LOTS_BY_ID.items():
        refs = [c for c in (lot.arcgis_max_cap, lot.parkendd_total) if c]
        if refs:
            out[lot_id] = HARD_LIMIT_FACTOR * max(refs)
    return out


def capacity_period(lot_id: pd.Series, ts_utc: pd.Series) -> pd.Series:
    """Label like ``lago`` or ``seerheincenter@2019-01-01`` (see ``CAPACITY_BREAKS``)."""
    label = lot_id.astype(str).copy()
    for lot, breaks in CAPACITY_BREAKS.items():
        for b in breaks:
            after = (lot_id == lot) & (ts_utc >= pd.Timestamp(b, tz=TZ))
            label[after] = f"{lot}@{b}"
    return label


def effective_capacity(df: pd.DataFrame, valid_so_far: pd.Series) -> dict[str, float]:
    """Spaces available to short-term parkers as observed: high quantile of valid free counts,
    per capacity period."""
    q = df[valid_so_far].groupby("capacity_period")["free"].quantile(EFFECTIVE_CAPACITY_QUANTILE)
    return {str(k): float(v) for k, v in q.items()}


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, CleaningStats]:
    """Flag every reading. Returns (clean_df, stats)."""
    stats = CleaningStats(raw_rows=len(raw))
    bad = raw["ts_utc"].isna() | raw["free"].isna()
    stats.unparseable = int(bad.sum())
    df = raw[~bad].copy()
    df["lot_id"] = df["lot_id"].astype(str)

    df = _drop_superseded_backup(df, stats)
    df = _deduplicate(df, stats)
    df["free"] = df["free"].astype("int64")
    df["ts_local"] = df["ts_utc"].dt.tz_convert(TZ)
    df["from_backup"] = df["is_backup"]

    prev = df.groupby("lot_id")["ts_utc"].shift()
    df["gap_before_min"] = (df["ts_utc"] - prev).dt.total_seconds() / 60
    df["gap_before"] = df["gap_before_min"] > GAP_MIN

    df = _runs(df)
    df["negative"] = df["free"] < 0
    df["stuck_long"] = df["run_hours"] >= STUCK_LONG_H
    df["stuck_day"] = (df["free"] > 0) & (df["run_day_overlap_h"] >= STUCK_DAY_H)
    df["zero_closed"] = (
        (df["free"] == 0)
        & (df["run_hours"] >= ZERO_CLOSED_MIN_H)
        & (df["run_day_overlap_h"] < ZERO_CLOSED_MAX_DAY_OVERLAP_H)
    )

    df["capacity_period"] = capacity_period(df["lot_id"], df["ts_utc"])
    hard = df["lot_id"].map(hard_limits())
    above_hard = (df["free"] > hard).fillna(False).astype(bool)
    pre_valid = ~df[["negative", "stuck_long", "stuck_day", "zero_closed"]].any(axis=1)
    stats.effective_capacity = effective_capacity(df, pre_valid & ~above_hard)
    cap_eff = df["capacity_period"].map(stats.effective_capacity)
    df["capacity_effective"] = cap_eff
    df["implausible_high"] = above_hard | (df["free"] > IMPLAUSIBLE_FACTOR * cap_eff)
    # A run of 0 surrounded by high values is a feed glitch: a car park cannot go from 900 free
    # to full and back within minutes. Real fill-ups approach 0 gradually.
    neighbours = df[["run_prev_free", "run_next_free"]].min(axis=1, skipna=True)
    df["zero_dip"] = (
        (df["free"] == 0) & (neighbours > ZERO_DIP_NEIGHBOUR_SHARE * cap_eff) & ~df["stuck_long"]
    )

    official = df["lot_id"].map(lambda x: LOTS_BY_ID[x].arcgis_max_cap).astype("Float64")
    df["capacity_official"] = official
    df["above_official_capacity"] = (df["free"] > official).fillna(False).astype(bool)
    censor = df["lot_id"].map(CENSOR_AT)
    df["censored_high"] = (df["free"] >= censor).fillna(False).astype(bool)

    df["valid"] = ~df[INVALID_FLAGS].any(axis=1)
    occ = 1 - df["free"] / df["capacity_effective"]
    df["occupancy"] = occ.clip(0, 1).where(df["valid"])

    stats.per_lot = flag_summary(df)
    cols = [
        "lot_id",
        "ts_utc",
        "ts_local",
        "free",
        "occupancy",
        "valid",
        *INVALID_FLAGS,
        *INFO_FLAGS,
        "gap_before",
        "gap_before_min",
        "run_hours",
        "run_day_overlap_h",
        "capacity_period",
        "capacity_effective",
        "capacity_official",
        "source_file",
    ]
    out = df[cols].copy()
    out["lot_id"] = out["lot_id"].astype("category")
    out["source_file"] = out["source_file"].astype(str).astype("category")
    out["capacity_period"] = out["capacity_period"].astype("category")
    return out, stats


def flag_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Rows per lot and share flagged by each rule (a row can carry several flags)."""
    flags = [*INVALID_FLAGS, "censored_high", "above_official_capacity", "dup_conflict"]
    g = df.groupby("lot_id", observed=True)
    out = g.size().rename("rows").to_frame()
    for f in flags:
        out[f] = g[f].sum()
    out["valid"] = g["valid"].sum()
    out["valid_pct"] = (100 * out["valid"] / out["rows"]).round(1)
    out.loc["all"] = out.sum(numeric_only=True)
    out.loc["all", "valid_pct"] = round(100 * out.loc["all", "valid"] / out.loc["all", "rows"], 1)
    return out


def to_grid(clean_df: pd.DataFrame, freq: str = "15min", max_fill_bins: int = 2) -> pd.DataFrame:
    """Regular UTC grid per lot from valid readings.

    ``free`` = mean of the valid readings in [t, t+15 min). Empty bins are filled by linear
    interpolation only for runs of at most ``max_fill_bins`` bins (30 min), flagged
    ``interpolated``; longer gaps stay missing.
    """
    v = clean_df[clean_df["valid"]]
    frames = []
    for lot, d in v.groupby("lot_id", observed=True):
        g = d.assign(bin=d["ts_utc"].dt.floor(freq)).groupby("bin")
        b = g["free"].agg(["mean", "size"])
        b["cap"] = g["capacity_effective"].max()
        idx = pd.date_range(b.index.min(), b.index.max(), freq=freq, tz="UTC", name="ts_utc")
        b = b.reindex(idx)
        missing = b["mean"].isna()
        run = (missing != missing.shift()).cumsum()
        run_len = missing.groupby(run).transform("size")
        fillable = missing & (run_len <= max_fill_bins)
        filled = b["mean"].interpolate(limit_area="inside")
        free = b["mean"].where(~fillable, filled)
        cap = b["cap"].ffill().bfill()
        frames.append(
            pd.DataFrame(
                {
                    "lot_id": lot,
                    "ts_utc": idx,
                    "free": free.to_numpy(),
                    "n_readings": b["size"].fillna(0).astype(int).to_numpy(),
                    "interpolated": (fillable & free.notna()).to_numpy(),
                    "capacity_effective": cap.to_numpy(),
                }
            )
        )
    grid = pd.concat(frames, ignore_index=True)
    grid["ts_local"] = grid["ts_utc"].dt.tz_convert(TZ)
    grid["occupancy"] = (1 - grid["free"] / grid["capacity_effective"]).clip(0, 1)
    grid["lot_id"] = grid["lot_id"].astype("category")
    return grid[
        [
            "lot_id",
            "ts_utc",
            "ts_local",
            "free",
            "occupancy",
            "n_readings",
            "interpolated",
            "capacity_effective",
        ]
    ]
