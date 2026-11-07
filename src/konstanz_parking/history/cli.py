"""Command implementations for the history pipeline (kept out of the collector's import path)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from konstanz_parking.history import coverage as cov
from konstanz_parking.history.load import load_raw


def coverage(dump_dir: Path, reports: Path) -> None:
    """Raw coverage per lot and month -> CSV tables + heatmap; prints the 2020 window."""
    tables, figures = reports / "tables", reports / "figures"
    tables.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)

    raw = load_raw(dump_dir)
    daily = cov.daily_coverage(raw)
    monthly = cov.monthly_coverage(daily)
    monthly.to_csv(tables / "coverage_raw_monthly.csv", index=False)
    cov.plot_heatmap(
        monthly,
        figures / "coverage_raw_heatmap.png",
        value="pct_usable_days",
        title="Raw data: share of usable days per month (≥80 % of slots, values not constant)",
    )

    window = monthly[
        (monthly["month"] >= pd.Period("2020-01", "M"))
        & (monthly["month"] <= pd.Period("2020-09", "M"))
    ]
    print("\n% of 5-min slots present (raw), 2020-01..2020-09\n")
    print(cov.to_markdown(cov.pivot(window, "pct_slots")))
    print("\n% usable days (raw), 2020-01..2020-09\n")
    print(cov.to_markdown(cov.pivot(window, "pct_usable_days")))
    print(
        f"\nwrote {tables / 'coverage_raw_monthly.csv'} and {figures / 'coverage_raw_heatmap.png'}"
    )
