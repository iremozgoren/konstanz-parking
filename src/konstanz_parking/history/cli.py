"""Command implementations for the history pipeline (kept out of the collector's import path)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from konstanz_parking.history import coverage as cov
from konstanz_parking.history.load import load_raw

# Coverage after cleaning is measured over local daytime only: several car parks are closed at
# night, and their night readings (0 free) are flagged as "closed", not as missing sensors.
DAYTIME_HOURS = (7, 20)


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


def clean(dump_dir: Path, processed: Path, reports: Path) -> None:
    """Flag every reading, write the cleaned long table and the 15-min grid as Parquet."""
    import json

    from konstanz_parking.history.clean import clean as run_clean
    from konstanz_parking.history.clean import to_grid

    processed.mkdir(parents=True, exist_ok=True)
    tables = reports / "tables"
    tables.mkdir(parents=True, exist_ok=True)

    raw = load_raw(dump_dir)
    df, stats = run_clean(raw)
    df.to_parquet(processed / "parkendd_clean.parquet", index=False)
    grid = to_grid(df)
    grid.to_parquet(processed / "parkendd_15min.parquet", index=False)

    figures = reports / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    daily = cov.daily_coverage(df, mask=df["valid"], hours=DAYTIME_HOURS)
    monthly = cov.monthly_coverage(daily)
    monthly.to_csv(tables / "coverage_valid_daytime_monthly.csv", index=False)
    cov.plot_heatmap(
        monthly,
        figures / "coverage_valid_heatmap.png",
        value="pct_usable_days",
        title="After cleaning: share of usable days per month (≥80 % valid slots, 07-20 h)",
    )

    stats.per_lot.to_csv(tables / "cleaning_flags_per_lot.csv")
    stats.backup_agreement.to_csv(tables / "backup_agreement.csv", index=False)
    summary = {
        "raw_rows": stats.raw_rows,
        "unparseable": stats.unparseable,
        "backup_superseded": stats.backup_superseded,
        "exact_duplicates": stats.exact_duplicates,
        "conflicting_duplicates": stats.conflicting_duplicates,
        "clean_rows": len(df),
        "valid_rows": int(df["valid"].sum()),
        "grid_rows": len(grid),
        "grid_non_missing": int(grid["free"].notna().sum()),
        "grid_interpolated": int(grid["interpolated"].sum()),
        "effective_capacity": stats.effective_capacity,
    }
    (tables / "cleaning_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(stats.per_lot.to_string())
    print(stats.backup_agreement.to_string())
    window = monthly[
        (monthly["month"] >= pd.Period("2020-01", "M"))
        & (monthly["month"] <= pd.Period("2020-09", "M"))
    ]
    print("\n% usable days after cleaning (07-20 h), 2020-01..2020-09\n")
    print(cov.to_markdown(cov.pivot(window, "pct_usable_days")))
