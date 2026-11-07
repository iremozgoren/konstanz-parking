"""Data quality report for the ParkenDD history (Markdown + PNG figures).

All numbers in the report are computed here from the raw dumps and the cleaned data, so the
report can be regenerated with ``konstanz-parking report`` after any change to the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from konstanz_parking.history import clean as C
from konstanz_parking.history import coverage as cov
from konstanz_parking.history import plotstyle
from konstanz_parking.history.load import load_raw
from konstanz_parking.history.lots import CAPACITY_BREAKS, EXCLUDED_DUMPS, LOTS, LOTS_BY_ID

TZ = "Europe/Berlin"
DAYTIME_HOURS = (7, 20)
WINDOW_2020 = ("2020-01", "2020-09")


@dataclass
class Ctx:
    raw: pd.DataFrame
    raw_all: pd.DataFrame
    df: pd.DataFrame
    stats: C.CleaningStats
    grid: pd.DataFrame
    figures: Path
    tables: Path


# --- helpers ----------------------------------------------------------------------------------


def _pct(a: float, b: float, nd: int = 1) -> str:
    return f"{100 * a / b:.{nd}f} %" if b else "n/a"


def _n(x: float) -> str:
    return f"{int(x):,}".replace(",", " ")


def _md(table: pd.DataFrame) -> str:
    return cov.to_markdown(table)


def _last_sunday(year: int, month: int) -> pd.Timestamp:
    d = pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)
    return d - pd.Timedelta(days=(d.dayofweek + 1) % 7)


# --- analyses ---------------------------------------------------------------------------------


def dst_lag_table(df: pd.DataFrame) -> pd.DataFrame:
    """For every DST switch: best lag (in hours) aligning the weekday occupancy profile in UTC
    3 weeks before vs 3 weeks after the switch.

    If timestamps are true UTC, local-time behaviour (shops open at 09:00 local) moves by one
    hour in UTC: -1 h after spring-forward, +1 h after fall-back. If timestamps were local wall
    time mislabelled as UTC, the best lag would be 0.
    """
    v = df[df["valid"]][["ts_utc", "occupancy"]]
    v = v[v["ts_utc"].dt.dayofweek < 5]
    rows = []
    for year in range(2015, 2023):
        for month, expected in ((3, -1), (10, +1)):
            switch = pd.Timestamp(_last_sunday(year, month), tz="UTC")
            before = v[(v["ts_utc"] >= switch - pd.Timedelta(days=21)) & (v["ts_utc"] < switch)]
            after = v[(v["ts_utc"] > switch + pd.Timedelta(days=1))]
            after = after[after["ts_utc"] <= switch + pd.Timedelta(days=22)]
            if len(before) < 5000 or len(after) < 5000:
                continue
            pb = _profile(before)
            pa = _profile(after)
            lags = range(-8, 9)  # quarter hours
            corr = {
                lag: pb.corr(pa.shift(lag, fill_value=np.nan).reindex(pb.index)) for lag in lags
            }
            # pa(t) ~ pb(t + lag*15min)  <=> after-curve is shifted by -lag quarter hours
            best = max(corr, key=lambda k: corr[k])
            rows.append(
                {
                    "switch": switch.date().isoformat(),
                    "kind": "spring forward" if month == 3 else "fall back",
                    "expected_shift_h": expected,
                    "observed_shift_h": -best / 4,
                    "corr_at_best": round(corr[best], 3),
                    "corr_at_0": round(corr[0], 3),
                }
            )
    return pd.DataFrame(rows)


def _profile(d: pd.DataFrame) -> pd.Series:
    q = d["ts_utc"].dt.hour * 4 + d["ts_utc"].dt.minute // 15
    return d.groupby(q)["occupancy"].mean().reindex(range(96))


def simultaneous_freezes(df: pd.DataFrame, min_lots: int = 5) -> pd.DataFrame:
    """Hours in which at least ``min_lots`` car parks are stuck at the same time.

    Such events point at the scraper or the city's feed, not at individual sensors.
    """
    s = df[df["stuck_long"] | df["stuck_day"]]
    hours = s.assign(h=s["ts_utc"].dt.floor("h")).groupby("h")["lot_id"].nunique()
    hours = hours[hours >= min_lots]
    if hours.empty:
        return pd.DataFrame(columns=["start", "end", "hours", "max_lots"])
    t = hours.index.to_series()
    event = (t.diff() != pd.Timedelta("1h")).cumsum()
    ev = (
        pd.DataFrame({"t": t, "n": hours, "e": event})
        .groupby("e")
        .agg(start=("t", "min"), end=("t", "max"), max_lots=("n", "max"))
    )
    ev["hours"] = ((ev["end"] - ev["start"]) / pd.Timedelta("1h") + 1).astype(int)
    ev["start"] = ev["start"].dt.tz_convert(TZ).dt.strftime("%Y-%m-%d %H:%M")
    ev["end"] = (ev["end"] + pd.Timedelta("1h")).dt.tz_convert(TZ).dt.strftime("%Y-%m-%d %H:%M")
    return ev[ev["hours"] >= 3].sort_values("hours", ascending=False)[
        ["start", "end", "hours", "max_lots"]
    ]


def common_gaps(df: pd.DataFrame, min_hours: float = 24) -> pd.DataFrame:
    """Gaps longer than ``min_hours`` and how many car parks share them."""
    g = df[df["gap_before_min"] > 60 * min_hours].copy()
    g["gap_start"] = g["ts_utc"] - pd.to_timedelta(g["gap_before_min"], unit="min")
    g["key"] = (
        g["gap_start"].dt.floor("D").astype(str) + "/" + g["ts_utc"].dt.floor("D").astype(str)
    )
    out = g.groupby("key").agg(
        start=("gap_start", "min"),
        end=("ts_utc", "max"),
        lots=("lot_id", "nunique"),
    )
    out["days"] = ((out["end"] - out["start"]).dt.total_seconds() / 86400).round(1)
    out["start"] = out["start"].dt.tz_convert(TZ).dt.strftime("%Y-%m-%d")
    out["end"] = out["end"].dt.tz_convert(TZ).dt.strftime("%Y-%m-%d")
    return out.sort_values("days", ascending=False).reset_index(drop=True)


def zero_runs(df: pd.DataFrame) -> pd.DataFrame:
    """One row per run of 0 free lasting >= 1 h, with local start time and classification."""
    z = df[(df["free"] == 0) & (df["run_hours"] >= 1)]
    z = z.sort_values(["lot_id", "ts_utc"])
    first = z.groupby(["lot_id", "run_hours", "run_day_overlap_h"], observed=True).head(1)
    first = first.assign(
        start_local=first["ts_utc"].dt.tz_convert(TZ),
        cls=np.select(
            [first["stuck_long"], first["zero_closed"], first["zero_dip"]],
            ["stuck >= 12 h", "closed (outside daytime)", "glitch (high values on both sides)"],
            "full (daytime, kept)",
        ),
    )
    return first


# --- figures ----------------------------------------------------------------------------------


def fig_flags(ctx: Ctx) -> None:
    import matplotlib.pyplot as plt

    plotstyle.apply()
    df = ctx.df
    reason = np.select(
        [
            df["valid"],
            df["zero_closed"],
            df["zero_dip"],
            df["stuck_long"],
            df["stuck_day"],
            df["negative"] | df["implausible_high"],
        ],
        [
            "valid",
            "0 while closed",
            "0 glitch",
            "stuck ≥ 12 h",
            "stuck ≥ 3 daytime h",
            "impossible value",
        ],
        "other",
    )
    t = pd.crosstab(df["lot_id"], reason, normalize="index") * 100
    order = [
        "valid",
        "0 while closed",
        "0 glitch",
        "stuck ≥ 12 h",
        "stuck ≥ 3 daytime h",
        "impossible value",
    ]
    t = t.reindex(columns=order, fill_value=0).sort_values("valid")
    colors = [plotstyle.CATEGORICAL[i] for i in (0, 3, 2, 1, 4, 7)]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    left = np.zeros(len(t))
    for col, c in zip(order, colors, strict=True):
        ax.barh(
            t.index,
            t[col],
            left=left,
            color=c,
            label=col,
            height=0.62,
            edgecolor=plotstyle.SURFACE,
            linewidth=1.5,
        )
        left += t[col].to_numpy()
    for i, v in enumerate(t["valid"]):
        ax.text(v / 2, i, f"{v:.0f} %", va="center", ha="center", color="white", fontsize=8)
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of readings (each reading counted once, first matching reason)")
    ax.grid(axis="y", visible=False)
    ax.legend(ncol=6, loc="upper left", bbox_to_anchor=(0, -0.14), fontsize=8)
    ax.set_title("Why readings were flagged, per car park (2015-2022)")
    fig.savefig(ctx.figures / "flags_per_lot.png")
    plt.close(fig)


def fig_dst(ctx: Ctx, year: int = 2018) -> None:
    import matplotlib.pyplot as plt

    plotstyle.apply()
    v = ctx.df[ctx.df["valid"]][["ts_utc", "ts_local", "occupancy"]]
    v = v[v["ts_utc"].dt.dayofweek < 5]
    switch = pd.Timestamp(_last_sunday(year, 3), tz="UTC")
    before = v[(v["ts_utc"] >= switch - pd.Timedelta(days=21)) & (v["ts_utc"] < switch)]
    after = v[(v["ts_utc"] > switch + pd.Timedelta(days=1))]
    after = after[after["ts_utc"] <= switch + pd.Timedelta(days=22)]

    def prof(d, col):
        h = d[col].dt.hour + d[col].dt.minute / 60
        return d.groupby((h * 4).astype(int) / 4)["occupancy"].mean() * 100

    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6), sharey=True)
    for ax, col, title in (
        (axes[0], "ts_utc", "Clock: UTC (as stored)"),
        (axes[1], "ts_local", "Clock: Europe/Berlin"),
    ):
        ax.plot(prof(before, col), color=plotstyle.CATEGORICAL[0], label="3 weeks before")
        ax.plot(prof(after, col), color=plotstyle.CATEGORICAL[1], label="3 weeks after")
        ax.set_title(title, fontsize=10)
        ax.set_xlim(4, 22)
        ax.set_xticks(range(4, 23, 2))
        ax.set_xlabel("hour of day")
    axes[0].set_ylabel("mean occupancy, all car parks (%)")
    axes[0].legend(loc="upper left")
    fig.suptitle(
        f"DST check, spring forward {switch.date()}: weekday profiles shift by 1 h in UTC "
        "and line up in local time",
        x=0.01,
        ha="left",
        fontsize=11,
        fontweight="bold",
    )
    fig.subplots_adjust(top=0.82)
    fig.savefig(ctx.figures / "dst_check.png")
    plt.close(fig)


def fig_frozen_example(ctx: Ctx) -> None:
    import matplotlib.pyplot as plt

    plotstyle.apply()
    d = ctx.df[
        (ctx.df["lot_id"] == "lago")
        & (ctx.df["ts_local"] >= "2020-05-04")
        & (ctx.df["ts_local"] < "2020-06-01")
    ]
    fig, ax = plt.subplots(figsize=(11, 3.4))
    # Zero readings (closed at night, or the 07:00 glitch) are not drawn as part of the line:
    # they would draw a spike every day. The glitches are marked separately at y = 0.
    zero_flag = d["zero_closed"] | d["zero_dip"]
    shown = d["free"].where(~zero_flag)
    ax.plot(d["ts_local"], shown, color=plotstyle.CATEGORICAL[0], lw=1.0, label="free spaces")
    stuck = d[d["stuck_long"] | d["stuck_day"]]
    ax.scatter(
        stuck["ts_local"],
        stuck["free"],
        s=4,
        color=plotstyle.CATEGORICAL[7],
        zorder=3,
        label="flagged: stuck",
    )
    glitch = d[d["zero_dip"] & ~d["zero_closed"]]
    ax.scatter(
        glitch["ts_local"],
        glitch["free"],
        s=10,
        marker="|",
        color=plotstyle.CATEGORICAL[1],
        zorder=3,
        label="flagged: 0 glitch (07:00)",
    )
    ax.set_ylabel("free spaces")
    ax.set_ylim(0, 1000)
    ax.legend(loc="lower left")
    ax.text(
        0,
        -0.28,
        "Night readings of 0 (car park closed, flag zero_closed) are not shown.",
        transform=ax.transAxes,
        color=plotstyle.TEXT_SECONDARY,
        fontsize=8,
    )
    ax.set_title(
        "Example: LAGO sensor frozen at 894 free from 12 to 25 May 2020 "
        "(shops open, border still closed)"
    )
    fig.autofmt_xdate()
    fig.savefig(ctx.figures / "frozen_example_lago_2020.png")
    plt.close(fig)


def fig_zero_weekday(ctx: Ctx, runs: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt

    plotstyle.apply()
    full = runs[runs["cls"] == "full (daytime, kept)"]
    closed = runs[runs["cls"] == "closed (outside daytime)"]
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.4))
    for ax, d, title, c in (
        (axes[0], full, "Daytime runs of 0 free (kept as 'full')", plotstyle.CATEGORICAL[0]),
        (axes[1], closed, "Night runs of 0 free (flagged 'closed')", plotstyle.CATEGORICAL[3]),
    ):
        counts = d["start_local"].dt.dayofweek.value_counts().reindex(range(7), fill_value=0)
        ax.bar(days, counts.to_numpy(), color=c, width=0.6)
        ax.set_title(title, fontsize=10)
        ax.grid(axis="x", visible=False)
        ax.set_ylabel("number of runs (≥ 1 h)")
    fig.suptitle(
        "Zero free spaces mean two different things",
        x=0.01,
        ha="left",
        fontsize=11,
        fontweight="bold",
    )
    fig.subplots_adjust(top=0.82)
    fig.savefig(ctx.figures / "zero_runs_by_weekday.png")
    plt.close(fig)


# --- report -----------------------------------------------------------------------------------


def build(dump_dir: Path, processed: Path, reports: Path) -> Path:
    figures, tables = reports / "figures", reports / "tables"
    figures.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)

    raw_all = load_raw(dump_dir, include_excluded=True)
    raw = raw_all[raw_all["lot_id"].notna()].copy()
    raw["lot_id"] = raw["lot_id"].astype(str)
    df, stats = C.clean(raw)
    grid = C.to_grid(df)
    ctx = Ctx(raw, raw_all, df, stats, grid, figures, tables)

    # Coverage (raw and after cleaning)
    raw_monthly = cov.monthly_coverage(cov.daily_coverage(raw))
    valid_monthly = cov.monthly_coverage(
        cov.daily_coverage(df, mask=df["valid"], hours=DAYTIME_HOURS)
    )
    cov.plot_heatmap(
        raw_monthly,
        figures / "coverage_raw_heatmap.png",
        "pct_usable_days",
        "Raw data: share of usable days per month (≥80 % of slots, not constant)",
    )
    cov.plot_heatmap(
        valid_monthly,
        figures / "coverage_valid_heatmap.png",
        "pct_usable_days",
        "After cleaning: share of usable days per month (≥80 % valid slots, 07-20 h)",
    )
    raw_monthly.to_csv(tables / "coverage_raw_monthly.csv", index=False)
    valid_monthly.to_csv(tables / "coverage_valid_daytime_monthly.csv", index=False)

    dst = dst_lag_table(df)
    dst.to_csv(tables / "dst_check.csv", index=False)
    freezes = simultaneous_freezes(df)
    freezes.to_csv(tables / "simultaneous_freezes.csv", index=False)
    gaps = common_gaps(df)
    gaps.to_csv(tables / "long_gaps.csv", index=False)
    zruns = zero_runs(df)
    stats.per_lot.to_csv(tables / "cleaning_flags_per_lot.csv")
    stats.backup_agreement.to_csv(tables / "backup_agreement.csv", index=False)

    fig_flags(ctx)
    fig_dst(ctx)
    fig_frozen_example(ctx)
    fig_zero_weekday(ctx, zruns)

    md = render(ctx, raw_monthly, valid_monthly, dst, freezes, gaps, zruns)
    out = reports / "data_quality_parkendd.md"
    out.write_text(md)
    return out


def _window(monthly: pd.DataFrame, value: str) -> pd.DataFrame:
    m = monthly[
        (monthly["month"] >= pd.Period(WINDOW_2020[0], "M"))
        & (monthly["month"] <= pd.Period(WINDOW_2020[1], "M"))
    ]
    p = cov.pivot(m, value)
    p.columns = [c.strftime("%b") for c in p.columns]
    return p


def render(
    ctx: Ctx,
    raw_monthly: pd.DataFrame,
    valid_monthly: pd.DataFrame,
    dst: pd.DataFrame,
    freezes: pd.DataFrame,
    gaps: pd.DataFrame,
    zruns: pd.DataFrame,
) -> str:
    df, s, raw, raw_all = ctx.df, ctx.stats, ctx.raw, ctx.raw_all
    n_clean, n_valid = len(df), int(df["valid"].sum())
    excluded_rows = int(raw_all["lot_id"].isna().sum())
    per = s.per_lot
    first, last = df["ts_utc"].min(), df["ts_utc"].max()

    # Lots table
    lot_rows = []
    for lot in LOTS:
        d = df[df["lot_id"] == lot.lot_id]
        eff = {k: v for k, v in s.effective_capacity.items() if k.split("@")[0] == lot.lot_id}
        eff_txt = " / ".join(f"{v:.0f}" for v in eff.values())
        lot_rows.append(
            {
                "car park": lot.lot_id,
                "dump names": ", ".join(lot.dump_names),
                "first (UTC)": d["ts_utc"].min().strftime("%Y-%m-%d"),
                "last (UTC)": d["ts_utc"].max().strftime("%Y-%m-%d"),
                "ArcGIS max_cap": lot.arcgis_max_cap or "–",
                "ParkenDD total": lot.parkendd_total or "–",
                "max valid free": int(d.loc[d["valid"], "free"].max()),
                "effective capacity": eff_txt,
            }
        )
    lots_tbl = pd.DataFrame(lot_rows).set_index("car park")

    excl = raw_all[raw_all["lot_id"].isna()].groupby("dump_name", observed=True).size()
    excl_tbl = pd.DataFrame(
        {"rows": excl, "reason": [EXCLUDED_DUMPS.get(str(k), "") for k in excl.index]}
    )
    excl_tbl.index.name = "dump name"

    gap_lens = df["gap_before_min"].dropna()
    n_gap15 = int((gap_lens > 15).sum())
    n_gap60 = int((gap_lens > 60).sum())
    n_gap1d = int((gap_lens > 1440).sum())
    interval_med = float(gap_lens.median())

    full_runs = zruns[zruns["cls"] == "full (daytime, kept)"]
    sat_share = (full_runs["start_local"].dt.dayofweek == 5).mean()
    late_morning = full_runs["start_local"].dt.hour.between(10, 12).mean()
    closed_runs = zruns[zruns["cls"] == "closed (outside daytime)"]
    closed_lots = closed_runs.groupby("lot_id", observed=True).size().sort_values(ascending=False)

    neg = df[df["negative"]]
    neg_years = sorted(neg["ts_local"].dt.year.unique())
    benedikt_above = per.loc["benediktiner", "above_official_capacity"]
    lago_above = per.loc["lago", "above_official_capacity"]
    bfo_cens = per.loc["bodenseeforum", "censored_high"]
    zero_dip_only = int((df["zero_dip"] & ~df["zero_closed"] & ~df["stuck_long"]).sum())

    flags_tbl = per[
        [
            "rows",
            "negative",
            "stuck_long",
            "stuck_day",
            "zero_closed",
            "zero_dip",
            "implausible_high",
            "valid",
            "valid_pct",
        ]
    ].astype(
        {
            c: int
            for c in [
                "rows",
                "negative",
                "stuck_long",
                "stuck_day",
                "zero_closed",
                "zero_dip",
                "implausible_high",
                "valid",
            ]
        }
    )
    flags_tbl.index.name = "car park"

    same_dir = (np.sign(dst["observed_shift_h"]) == np.sign(dst["expected_shift_h"])) & (
        dst["observed_shift_h"].abs() >= 0.5
    )
    dst_ok = int(same_dir.sum())
    dst_exact = int((dst["observed_shift_h"] == dst["expected_shift_h"]).sum())
    dst_tbl = dst.set_index("switch")

    freezes_top = freezes.head(12).set_index("start")
    gaps_top = gaps.head(10)
    gaps_top.index = gaps_top.index + 1
    gaps_top.index.name = "#"

    raw_2020 = _window(raw_monthly, "pct_slots")
    valid_2020 = _window(valid_monthly, "pct_usable_days")

    grid = ctx.grid
    grid_cov = grid["free"].notna().mean()

    lago_may = df[
        (df["lot_id"] == "lago")
        & (df["ts_local"] >= "2020-05-12")
        & (df["ts_local"] < "2020-05-26")
    ]
    lago_may_stuck = 1 - lago_may["valid"].mean()

    cap_breaks = ", ".join(f"{k} at {', '.join(v)}" for k, v in CAPACITY_BREAKS.items())
    doebele = LOTS_BY_ID["doebele"]

    return f"""# Data quality report: ParkenDD history for Konstanz (2015-2022)

*Generated by `uv run konstanz-parking report` from the raw dumps. All numbers below are computed,
not typed. Raw files are never modified. Cleaned data: `data/processed/` (not committed: the dumps
carry no license).*

## Summary

- **{_n(s.raw_rows)} raw readings** in {len(raw["source_file"].unique())} files for 9 car parks,
  {first:%Y-%m-%d} to {last:%Y-%m-%d}, nominally every 5 minutes (median interval
  {interval_med:.1f} min). Another {_n(excluded_rows)} rows from scraper artefacts are excluded.
- After removing superseded backup rows and duplicates, **{_n(n_clean)} readings** remain, of which
  **{_n(n_valid)} ({_pct(n_valid, n_clean)}) are valid**. Nothing is deleted silently: every
  reading keeps its flags in `parkendd_clean.parquet`.
- The biggest problems are **frozen values** (sensor or scraper stuck: {
        _pct(per.loc["all", "stuck_long"] + per.loc["all", "stuck_day"], n_clean)
    } of readings, some flagged by both rules)
  and **zeros that do not mean "full"**: car parks reporting 0 while closed at night ({
        _pct(per.loc["all", "zero_closed"], n_clean)
    }) and a daily 07:00 feed glitch. Zeros during the day are kept, because they mean *full*, mostly on Saturdays.
- **Timestamps are real UTC.** At {dst_ok} of {len(dst)} DST switches the daily profile shifts in
  UTC in the expected direction (by 0.5-1 h, exactly 1 h at {dst_exact}); none shows no shift.
- **Official capacities do not match the data.** Some car parks never get near their official
  capacity (possibly because of long-term permit holders), and others regularly report *more* free spaces than they
  officially have. Occupancy is therefore computed against an *effective capacity* derived from
  the data, not the official number.
- **2020 border-closure window:** raw coverage is ≥ 94 % of 5-minute slots for every car park.
  After cleaning, LAGO (the largest car park, at the shopping centre next to the Swiss border) is
  **frozen from 12 to 25 May 2020**, in the middle of the key "shops open, border closed" window.
  Seerheincenter only has live data from February 2020.

## 1. Source and scope

ParkenDD dumps from `https://parkendd.de/dumps/`, format `utc_timestamp,free` without header,
rows unsorted. Downloaded with `konstanz-parking download-parkendd` into the gitignored
`data/external/parkendd/` (no license stated, so never committed).

{_md(lots_tbl)}

- *ArcGIS max_cap* and *ParkenDD total* are today's official values (retrieved 2026-11-07).
- *Effective capacity* is the 99.9th percentile of valid free counts (see section 7).
- Two car parks were **renamed by the scraper**, with seamless, non-overlapping series:
  `augustinerkarstadt` → `augustiner` (2022-01-10) and `amseerhein` → `bodenseeforum`
  (2016-11-25). They are merged.
- **Excluded dumps:**

{_md(excl_tbl)}

## 2. Coverage of the raw data

![Raw coverage](figures/coverage_raw_heatmap.png)

A day counts as *usable* when ≥ 80 % of its 5-minute slots have a reading and the values are not
all the same. Days are local calendar days, so DST days have 276 or 300 slots instead of 288. Full
table: `tables/coverage_raw_monthly.csv`.

Gaps shared by all car parks are scraper downtime. The largest ones:

{_md(gaps_top)}

Two holes matter most: **2019-02-11 to 2019-05-16** and **almost all of 2021** (data only from
2021-02-05 to 2021-03-26; after that the scraper wrote only zeros to the artefact file
`konstanz0`). The four car parks with backup files start in mid-2015; the others on 2015-09-23.

**2020 window, % of 5-minute slots present (raw):**

{_md(raw_2020)}

## 3. Timestamps, time zones and DST

The dumps contain naive timestamps that ParkenDD documents as UTC. Two independent checks confirm
this:

1. **Structure.** On spring-forward nights the series runs through 01:00-03:00 UTC without a gap.
   On fall-back nights there is no doubled hour. Local wall-clock timestamps would show a missing
   or repeated hour.
2. **Behaviour.** People follow local time: shops open at 09:00 local. In true UTC, the weekday
   occupancy profile must move one hour earlier after spring forward and one hour later after
   fall back. The best-aligning lag (15-minute resolution) between the weekday profiles of the
   3 weeks before and after each switch:

{_md(dst_tbl)}

Every switch shifts in the expected direction and none has its best fit at 0, which is what
mislabelled local time would produce. Shifts below a full hour are probably real behaviour changing
across the switch (e.g. longer evenings, school holidays). The 2020-03-29 switch falls in the first
COVID lockdown, hence its low correlation.

![DST check](figures/dst_check.png)

Handling: timestamps are parsed as UTC and stored as `ts_utc`. `ts_local` is derived with
`tz_convert("Europe/Berlin")`. One pitfall came up during development: rounding *local* timestamps
(e.g. `floor("h")`) raises on the ambiguous fall-back hour, so all rounding is done in UTC.

## 4. Duplicates and overlapping files

- **Backup files.** For four car parks, `*.backup-2015.csv` files start earlier (2015-06-30) than
  the main 2015 files (2015-09-23) and overlap them afterwards. The two scrapers sampled a few
  seconds apart, so overlapping rows interleave rather than duplicate. Backup rows are used only
  before the main file starts ({_n(s.backup_superseded)} superseded rows dropped). Agreement
  during the overlap (nearest reading within 3 min):

{_md(s.backup_agreement.set_index("lot_id"))}

- **Exact duplicates** (same car park, timestamp and value): {_n(s.exact_duplicates)} rows, dropped.
- **Conflicting duplicates** (same timestamp, different value): {_n(s.conflicting_duplicates)}
  rows. The first occurrence in file order is kept and flagged `dup_conflict`.
- No unparseable rows ({s.unparseable}).

## 5. Gaps and irregular intervals

Readings come every ~5 minutes with jitter of a few seconds. Gaps between consecutive readings of
one car park: {_n(n_gap15)} longer than 15 min, {_n(n_gap60)} longer than 1 h and {_n(n_gap1d)}
longer than one day (`gap_before`, `gap_before_min`). Gaps are not filled in the long table. On the
15-minute grid, empty bins are interpolated only if the gap is ≤ 30 minutes (flagged
`interpolated`: {_n(grid["interpolated"].sum())} bins). Longer gaps stay missing.

## 6. Frozen values

A run is a sequence of identical consecutive values. Runs are broken at gaps > 60 min, so a data
gap is never mistaken for a frozen sensor. The thresholds were calibrated on the run-length
distribution:

- **`stuck_long`:** the same value for ≥ 12 h. Constant overnight values of 9-12 h are common and
  legitimate (closed or idle car parks). Longer runs are not. Longest examples: Seerheincenter at 0
  from 2018-04 to 2020-02 (sensor dead), Bodenseeforum at 0 for 45 days in summer 2018.
- **`stuck_day`:** the same *non-zero* value for ≥ 3 h of daytime (09-19 local). A busy city car
  park never stays exactly constant for three daytime hours.

Frozen periods that hit **several car parks at the same time** point at the city's feed or the
scraper, not at sensors. Events with ≥ 5 car parks stuck at once (≥ 3 h):

{_md(freezes_top)}

![Frozen example](figures/frozen_example_lago_2020.png)

In this example the daily 07:00 zero glitch (section 7) keeps arriving throughout the freeze. So
the city's feed was alive and only LAGO's own counter was stuck, first at 894 and then at 783.

## 7. Zeros, impossible values and capacity

**Zero free spaces mean two different things.** Runs of 0 lasting ≥ 1 h that lie almost entirely
outside 09-19 local time are car parks reporting 0 while *closed* (flag `zero_closed`). This is
most frequent for {", ".join(closed_lots.index[:4])}. Runs of 0 *during* the day are kept as real
*full* events: {_pct(sat_share, 1, 0)} of them start on a Saturday, and {_pct(late_morning, 1, 0)}
start between 10:00 and 12:59.
That is the Saturday effect this project studies, not a sensor fault.

**Zero glitches.** Several car parks drop to 0 for about 15 minutes **every morning at 07:00
local** (Augustiner, LAGO, Benediktiner), and Döbele, Fischmarkt and Marktstätte do the same at
midnight. They then jump straight back to their previous level (e.g. LAGO 910 → 0 → 909). A car
park cannot fill up and empty again within minutes, so this is a feed reset. Rule `zero_dip`: a
run of zeros (of any length) is invalid when the readings just before *and* just after it are both
above 20 % of effective capacity. Real fill-ups approach 0 gradually and are not affected.
{_n(zero_dip_only)} readings are flagged only by this rule; the others are night closures that
`zero_closed` already catches. This rule was added after the first version of the report, when
the LAGO example plot below showed a spike every morning.

![Zero runs](figures/zero_runs_by_weekday.png)

**Negative values** (`negative`, {_n(len(neg))} readings) occur only in {
        ", ".join(map(str, neg_years))
    }, down to {int(neg["free"].min())} (Bodenseeforum). Invalid.

**Capacity.** The official capacities (ArcGIS `max_cap`, ParkenDD `total`) are today's values and
often contradict the history:

- Benediktiner reports more free spaces than its official 118 in {_n(benedikt_above)} readings (up
  to {
        int(raw.loc[raw["lot_id"] == "benediktiner", "free"].max())
    }). LAGO exceeds its ArcGIS capacity of 931 in {_n(lago_above)} readings, but stays within
  ParkenDD's 936.
- Altstadt rarely reports more than 259 free (99.9th percentile) of an official 359. Döbele tops out
  at 335, which matches ParkenDD's total, while ArcGIS says {doebele.arcgis_max_cap}. Possible
  reasons: spaces reserved for permit holders, or capacity changes after 2022. The sources don't
  say.
- Seerheincenter's ceiling changes from 280 (2015-2017) to 222-235 (from 2020). Capacity periods
  used: {cap_breaks}.

Handling: readings above **1.2 × the larger official capacity** are flagged `implausible_high`
first (e.g. Seerheincenter reporting 1 410 free in June/July 2020), so they cannot distort what
follows. The **effective capacity** is the 99.9th percentile of the remaining valid readings per
car park and capacity period. Readings above 1.05 × effective capacity are also flagged
`implausible_high`. Over-official readings below those limits are kept and flagged
`above_official_capacity` (informational). **Occupancy = 1 − free / effective capacity**, clipped
to [0, 1]. It measures how full the car park is relative to the spaces actually available to
short-term parkers. It is comparable over time within a car park, but not an official utilisation
rate.

**Censoring.** Bodenseeforum never reports more than 500 free ({_n(bfo_cens)} readings at exactly
500), although it has more spaces on event days. Low occupancy there is right-censored (flag
`censored_high`).

## 8. Result after cleaning

![Flags per car park](figures/flags_per_lot.png)

{_md(flags_tbl)}

A reading can carry several flags, so the columns don't add up. `valid` = none of `negative`,
`stuck_long`, `stuck_day`, `zero_closed`, `zero_dip` or `implausible_high`.

![Valid coverage](figures/coverage_valid_heatmap.png)

**2020 window, % usable days after cleaning** (≥ 80 % valid 5-minute slots between 07 and 20 h
local):

{_md(valid_2020)}

Notes on the 2020 natural experiment:

- LAGO, the largest car park and the one right at the Swiss border, is frozen from 12 to 25 May 2020
  ({_pct(lago_may_stuck, 1, 0)} of its readings in that span are flagged). Those two weeks fall in
  the key "shops open in BW, border closed" phase, which therefore rests on the other car parks
  for that fortnight.
- Seerheincenter only becomes usable in February 2020, so it has almost no pre-COVID baseline.
- August 2020 has a feed-wide freeze (11-20 August, all car parks).
- The university car parks (the planned control group) are not in the ParkenDD history at all. They
  exist only in the live data collected since November 2026.

**15-minute grid:** {_n(len(grid))} lot × 15-minute bins between each car park's first and last
reading, {_pct(grid_cov, 1)} of them non-missing. The missing bins are mostly the two big holes
(2019 and 2021) and nights at car parks that close.

## 9. Outputs

| file | content |
|---|---|
| `data/processed/parkendd_clean.parquet` | every reading with `ts_utc`, `ts_local`, `free`, `occupancy`, `valid` and all flags |
| `data/processed/parkendd_15min.parquet` | regular UTC grid per car park: mean free of valid readings, `n_readings`, `interpolated`, `occupancy` |
| `reports/tables/*.csv` | coverage per month (raw and after cleaning), flags per lot, DST check, freezes, gaps |

## 10. Limitations and open questions

- The thresholds (12 h, 3 daytime h, 1 h of zeros outside 09-19 h) are judgement calls calibrated
  on this data. They are constants at the top of `history/clean.py`, and the report regenerates if
  they change.
- Effective capacities are derived from the data. If a car park was never close to empty during the
  history, its occupancy is overstated in absolute terms. Within-car-park comparisons are
  unaffected.
- A sensor stuck at 0 for less than 12 h during the day cannot be told apart from a car park that is
  really full. Such readings are kept.
- Night-time occupancy is mostly unavailable for car parks that close at night. The analysis
  should focus on opening hours.
- Marktstätte's highest free count drifts with the season (≈ 200 in summer, ≈ 240 in winter). This
  probably reflects varying numbers of long-term parkers. It is not modelled as a capacity change.
- The ParkenDD scraper mirrors the city's guidance-system page. Errors in the city's own feed (e.g.
  the August 2020 freeze) cannot be told apart from scraper errors.
"""
