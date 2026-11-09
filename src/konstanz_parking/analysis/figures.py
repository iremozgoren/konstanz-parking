"""Figures for ``reports/analysis.md`` (static PNGs, shared style from ``history/plotstyle``)."""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from konstanz_parking.analysis import natural_experiment as ne
from konstanz_parking.history import plotstyle as ps

GROUP_LABEL = {
    "lago": "LAGO (border-near shopping centre)",
    "centre": "City centre (5 car parks)",
    "less_shopping": "Less shopping-oriented (Benediktiner, Bodenseeforum)",
}
PHASES_2020 = [
    ("2020-03-18", "2020-04-19", "#ecebe7", "lockdown"),
    ("2020-04-20", "2020-06-14", "#dfeaf8", "shops open,\nno Swiss shoppers"),
]


def _shade(ax: plt.Axes, labels: bool = True) -> None:
    for a, b, colour, label in PHASES_2020:
        ax.axvspan(
            pd.Timestamp(a), pd.Timestamp(b) + pd.Timedelta(days=1), color=colour, lw=0, zorder=0
        )
        if labels:
            mid = pd.Timestamp(a) + (pd.Timestamp(b) - pd.Timestamp(a)) / 2
            ax.text(
                mid,
                0.98,
                label,
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="top",
                fontsize=7.5,
                color=ps.TEXT_SECONDARY,
            )
    ax.axvline(ne.REOPEN, color=ps.TEXT, lw=1, ls="--", zorder=1)


def _dates(ax: plt.Axes) -> None:
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))


def raw_weekly(res: ne.Results, path: Path) -> None:
    ps.apply()
    w = res.raw_weekly
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.4), sharey=True)
    for ax, g in zip(axes, ["lago", "centre", "less_shopping"], strict=True):
        _shade(ax, labels=ax is axes[0])
        for period, colour in (("2016–2019", ps.MUTED), ("2020", ps.CATEGORICAL[0])):
            s = w[(w["group"] == g) & (w["period"] == period)].sort_values("start")
            ax.plot(
                s["start"] + pd.Timedelta(days=3),
                s["y"],
                color=colour,
                label=period,
                marker="o",
                ms=3,
            )
        ax.set_title(GROUP_LABEL[g], fontsize=9.5)
        _dates(ax)
    axes[0].set_ylabel("Mean occupancy 10–18 h (%)")
    axes[0].legend(loc="lower left")
    fig.suptitle(
        "Weekly occupancy in 2020 vs the same weeks of 2016–2019 (shopping days)",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _event_axes(ax: plt.Axes, ev: pd.DataFrame, colour: str, jump: dict | None) -> None:
    x = ev["start"] + pd.Timedelta(days=3)
    ax.axhline(0, color=ps.TEXT_SECONDARY, lw=0.8)
    ax.errorbar(
        x,
        ev["est"],
        yerr=[ev["est"] - ev["lo"], ev["hi"] - ev["est"]],
        fmt="o",
        color=colour,
        ms=4,
        elinewidth=1.2,
        capsize=0,
    )
    if jump is not None:
        tb = jump["trend_bins"]
        sub = ev[ev["bin"].isin(tb)]
        k = sub["bin"].to_numpy(float)
        coef = np.polyfit(k, sub["est"].to_numpy(float), 1)
        kk = np.array([min(tb), 0.0])
        ax.plot(
            ne.REOPEN + pd.to_timedelta(kk * 7 + 3, unit="D"),
            np.polyval(coef, kk),
            color=ps.CATEGORICAL[1],
            lw=1.5,
            ls=":",
            label="Trend 20 Apr–14 Jun, extrapolated",
        )


def event_study(res: ne.Results, path: Path) -> None:
    ps.apply()
    fig, ax = plt.subplots(figsize=(9, 4.2))
    _shade(ax)
    _event_axes(ax, res.event, ps.CATEGORICAL[0], res.jump)
    for i, (label, day) in enumerate(ne.CONFOUNDER_DATES.items()):
        t = pd.Timestamp(day)
        ax.axvline(t, color=ps.MUTED, lw=0.8, ls="-", zorder=0.5)
        ax.text(
            t,
            0.02 + 0.07 * (i % 2),
            f" {label}",
            transform=ax.get_xaxis_transform(),
            fontsize=7,
            color=ps.TEXT_SECONDARY,
            rotation=0,
            ha="left",
            va="bottom",
        )
    _dates(ax)
    ax.set_ylabel("2020 vs 2016–2019, relative to 8–14 Jun (pp)")
    ax.set_title("Event study: weekly 2020 effect with 95 % CI (pre-specified)")
    ax.legend(loc="upper left", bbox_to_anchor=(0, 0.88))
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def event_study_long(res: ne.Results, path: Path) -> None:
    ps.apply()
    fig, ax = plt.subplots(figsize=(9, 3.6))
    _shade(ax)
    _event_axes(ax, res.event_long, ps.CATEGORICAL[0], None)
    pre = res.event_long[res.event_long["start"] < pd.Timestamp("2020-03-09")]
    ax.axhline(
        pre["est"].mean(),
        color=ps.CATEGORICAL[2],
        lw=1.2,
        ls="--",
        label=f"Mean of February/early March 2020 ({pre['est'].mean():+.1f} pp)",
    )
    _dates(ax)
    ax.set_ylabel("pp, relative to 8–14 Jun")
    ax.set_title("Exploratory: the same event study from February (pre-COVID level of 2020)")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def event_study_groups(res: ne.Results, path: Path) -> None:
    ps.apply()
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6), sharey=True)
    for i, (ax, g) in enumerate(zip(axes, ["lago", "centre", "less_shopping"], strict=True)):
        ev, jump = res.by_group[g]
        _shade(ax, labels=False)
        _event_axes(ax, ev, ps.CATEGORICAL[0], jump)
        j = jump["jump"]
        ax.set_title(
            f"{GROUP_LABEL[g]}\njump vs trend {j['est']:+.1f} pp [{j['lo']:+.1f}, {j['hi']:+.1f}]",
            fontsize=9,
        )
        _dates(ax)
        if i == 0:
            ax.legend(loc="lower right", fontsize=7)
    axes[0].set_ylabel("pp, relative to 8–14 Jun")
    fig.suptitle(
        "Exploratory: event study per car park group", x=0.01, ha="left", fontweight="bold"
    )
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def forest(
    rows: pd.DataFrame, path: Path, title: str, xlabel: str, main_kind: str = "main"
) -> None:
    """Point estimates with 95 % CIs, one row per estimate (top = first row)."""
    ps.apply()
    n = len(rows)
    fig, ax = plt.subplots(figsize=(8, 0.42 * n + 1.2))
    y = np.arange(n)[::-1]
    colours = [
        ps.CATEGORICAL[0] if k == main_kind else (ps.MUTED if k == "placebo" else ps.TEXT_SECONDARY)
        for k in rows["kind"]
    ]
    ax.axvline(0, color=ps.TEXT_SECONDARY, lw=0.8)
    for yi, (_, r), c in zip(y, rows.iterrows(), colours, strict=True):
        ax.plot([r["lo"], r["hi"]], [yi, yi], color=c, lw=2, solid_capstyle="round")
        ax.plot(r["est"], yi, "o", color=c, ms=6, mec=ps.SURFACE, mew=1.5)
        ax.text(
            max(r["hi"], 0),
            yi,
            f"  {r['est']:+.1f} [{r['lo']:+.1f}, {r['hi']:+.1f}]",
            va="center",
            fontsize=7.5,
            color=ps.TEXT_SECONDARY,
        )
    ax.set_yticks(y, rows["label"])
    ax.grid(axis="y", visible=False)
    lo, hi = rows["lo"].min(), rows["hi"].max()
    ax.set_xlim(min(lo, 0) - 0.05 * (hi - lo), hi + 0.45 * (hi - min(lo, 0)))
    ax.set_xlabel(xlabel)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fx_figure(res, path: Path) -> None:
    """Left: monthly CHF/EUR. Right: occupancy vs FX after removing season, trends and controls."""
    ps.apply()
    fx = res.fx.loc["2015-01":"2022-12"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.8), gridspec_kw={"width_ratios": [1.4, 1]})
    t = pd.PeriodIndex(fx.index, freq="M").to_timestamp()
    a1.plot(t, fx["chf_per_eur"], color=ps.CATEGORICAL[0])
    a1.axvspan(
        pd.Timestamp("2015-07-01"), pd.Timestamp("2020-03-01"), color="#dfeaf8", lw=0, zorder=0
    )
    a1.text(
        pd.Timestamp("2017-11-01"),
        0.03,
        "main sample",
        transform=a1.get_xaxis_transform(),
        ha="center",
        va="bottom",
        fontsize=8,
        color=ps.TEXT_SECONDARY,
    )
    a1.set_ylabel("CHF per EUR (lower = stronger franc)")
    a1.set_title("ECB reference rate, monthly mean")
    a1.xaxis.set_major_locator(mdates.YearLocator())
    a1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    r = res.resid
    x = r["x_res"] * 100  # log points ≈ %
    a2.axhline(0, color=ps.TEXT_SECONDARY, lw=0.8)
    a2.axvline(0, color=ps.TEXT_SECONDARY, lw=0.8)
    a2.scatter(x, r["y_res"], s=14, color=ps.CATEGORICAL[0], alpha=0.45, lw=0)
    main = res.table.iloc[0]
    slope = main["est"] / (100 * np.log(1.1))
    xx = np.array([x.min(), x.max()])
    a2.plot(
        xx,
        slope * xx,
        color=ps.CATEGORICAL[1],
        lw=2,
        label=f"Main: {main['est']:+.1f} pp per 10 % [{main['lo']:+.1f}, {main['hi']:+.1f}]",
    )
    a2.set_xlabel("Franc strength vs expected (%, residual)")
    a2.set_ylabel("Occupancy vs expected (pp, residual)")
    a2.set_title("After season, trends and controls")
    a2.legend(loc="upper left", fontsize=7.5)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
