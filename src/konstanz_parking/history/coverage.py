"""Coverage of the ParkenDD history per car park, per local day and per month.

A *slot* is a 5-minute UTC interval with at least one reading. Days and months are local
(Europe/Berlin) calendar days, so DST days have 276 or 300 expected slots instead of 288.
A day is *usable* when at least 80 % of its slots are present and the values are not constant.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from konstanz_parking.history import plotstyle

TZ = "Europe/Berlin"
SLOT = "5min"
USABLE_DAY_MIN_SHARE = 0.8


def expected_slots_per_day(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Number of 5-minute slots in each local calendar day from ``start`` to ``end`` (dates)."""
    days = pd.date_range(start, end, freq="D", tz=TZ)
    nxt = days + pd.DateOffset(days=1)
    minutes = (nxt.tz_convert("UTC") - days.tz_convert("UTC")).total_seconds() / 60
    return pd.Series((minutes / 5).astype(int), index=days.tz_localize(None).date, name="expected")


def daily_coverage(
    df: pd.DataFrame,
    mask: pd.Series | None = None,
    hours: tuple[int, int] | None = None,
) -> pd.DataFrame:
    """Per lot and local day: present slots, expected slots, distinct values, usable flag.

    ``df`` needs ``lot_id``, ``ts_utc`` (tz-aware UTC) and ``free``. ``mask`` optionally selects
    the rows that count (e.g. only valid readings after cleaning). ``hours=(7, 20)`` restricts
    both present and expected slots to that local-time window (useful after cleaning, because
    several car parks are closed at night and their night readings are flagged).
    """
    d = df if mask is None else df[mask]
    d = d.dropna(subset=["ts_utc", "free"])
    slot = d["ts_utc"].dt.floor(SLOT)
    local = slot.dt.tz_convert(TZ)
    if hours is not None:
        keep = (local.dt.hour >= hours[0]) & (local.dt.hour < hours[1])
        d, slot, local = d[keep], slot[keep], local[keep]
    local_date = local.dt.date
    g = pd.DataFrame(
        {"lot_id": d["lot_id"].astype(str), "date": local_date, "slot": slot, "free": d["free"]}
    ).groupby(["lot_id", "date"], observed=True)
    per_day = g.agg(slots=("slot", "nunique"), n_values=("free", "nunique")).reset_index()

    lots = sorted(df["lot_id"].dropna().astype(str).unique())
    ts = df["ts_utc"].dropna()
    exp = expected_slots_per_day(
        ts.min().tz_convert(TZ).normalize().tz_localize(None),
        ts.max().tz_convert(TZ).normalize().tz_localize(None),
    )
    full = pd.MultiIndex.from_product([lots, exp.index], names=["lot_id", "date"]).to_frame(
        index=False
    )
    if hours is not None:
        exp = pd.Series((hours[1] - hours[0]) * 12, index=exp.index)  # no DST switch in 07-20 h
    full["expected"] = np.tile(exp.to_numpy(), len(lots))
    out = full.merge(per_day, on=["lot_id", "date"], how="left")
    out[["slots", "n_values"]] = out[["slots", "n_values"]].fillna(0).astype(int)
    out["share"] = out["slots"] / out["expected"]
    out["usable"] = (out["share"] >= USABLE_DAY_MIN_SHARE) & (out["n_values"] > 1)
    return out


def monthly_coverage(daily: pd.DataFrame) -> pd.DataFrame:
    """Aggregate ``daily_coverage`` output to months."""
    d = daily.assign(month=pd.to_datetime(daily["date"]).dt.to_period("M"))
    m = (
        d.groupby(["lot_id", "month"])
        .agg(
            days=("date", "size"),
            slots=("slots", "sum"),
            expected=("expected", "sum"),
            usable_days=("usable", "sum"),
        )
        .reset_index()
    )
    m["pct_slots"] = (100 * m["slots"] / m["expected"]).round(1)
    m["pct_usable_days"] = (100 * m["usable_days"] / m["days"]).round(1)
    return m


def pivot(monthly: pd.DataFrame, value: str = "pct_slots") -> pd.DataFrame:
    return monthly.pivot(index="lot_id", columns="month", values=value)


def plot_heatmap(
    monthly: pd.DataFrame, path: Path, value: str = "pct_usable_days", title: str = ""
) -> None:
    """Lots x months heatmap of a coverage percentage."""
    import matplotlib.pyplot as plt

    plotstyle.apply()
    p = pivot(monthly, value)
    fig, ax = plt.subplots(figsize=(13, 0.42 * len(p) + 1.6))
    cmap = plotstyle.SEQUENTIAL.copy()
    cmap.set_bad(plotstyle.GRID)  # months with 0 % are drawn grey ("no data"), not pale blue
    values = np.ma.masked_less_equal(p.to_numpy(dtype=float), 0)
    im = ax.imshow(values, aspect="auto", cmap=cmap, vmin=0, vmax=100, interpolation="nearest")
    ax.set_yticks(range(len(p)), p.index)
    months = list(p.columns)
    ticks = [i for i, m in enumerate(months) if m.month in (1, 7)]
    ax.set_xticks(ticks, [f"{months[i].year}-{months[i].month:02d}" for i in ticks], rotation=0)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    # Mark the 2020 border-closure window.
    try:
        i0 = months.index(pd.Period("2020-03", "M"))
        i1 = months.index(pd.Period("2020-06", "M"))
        ax.axvspan(i0 - 0.5, i1 + 0.5, fill=False, edgecolor=plotstyle.CATEGORICAL[1], lw=1.5)
    except ValueError:
        pass
    cb = fig.colorbar(im, ax=ax, fraction=0.02, pad=0.01)
    cb.set_label("%")
    cb.outline.set_visible(False)
    ax.set_title(title or value)
    ax.text(
        0,
        -0.07,
        "Grey = no usable data. Orange box = March–June 2020 (border closure).",
        transform=ax.transAxes,
        color=plotstyle.TEXT_SECONDARY,
        fontsize=8,
        va="top",
    )
    fig.savefig(path)
    plt.close(fig)


def to_markdown(table: pd.DataFrame) -> str:
    """Small dependency-free Markdown table renderer (no ``tabulate`` needed)."""
    cols = [str(c) for c in table.columns]
    idx_name = table.index.name or ""
    lines = [
        "| " + " | ".join([idx_name, *cols]) + " |",
        "|" + "---|" * (len(cols) + 1),
    ]
    for idx, row in table.iterrows():
        cells = ["" if pd.isna(v) else (f"{v:g}" if isinstance(v, float) else str(v)) for v in row]
        lines.append("| " + " | ".join([str(idx), *cells]) + " |")
    return "\n".join(lines)
