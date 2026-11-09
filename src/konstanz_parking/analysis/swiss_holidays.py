"""Angle 2: Swiss (TG/ZH) holidays on German shopping days, 2015-2022.

Pre-specified in ``reports/analysis_plan.md``. Main estimate = coefficient on
``swiss_holiday_german_shopping_day`` (TG or ZH public or school holiday on a German shopping day),
daily level, all car parks, fixed effects car park x year-month and car park x weekday, clustered
by calendar week.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from konstanz_parking.analysis import panel
from konstanz_parking.analysis.fe import FEResult, feols

PERIODS = [("2015-07-01", "2020-03-15"), ("2022-04-01", "2022-12-31")]
XMAS = ("12-20", "01-06")
TREAT = "swiss_holiday_german_shopping_day"
FE = [["lot_id", "ym"], ["lot_id", "day_of_week"]]
PLACEBO_SHIFT = 14


def _in_periods(dates: pd.Series) -> pd.Series:
    m = pd.Series(False, index=dates.index)
    for a, b in PERIODS:
        m |= (dates >= pd.Timestamp(a)) & (dates <= pd.Timestamp(b))
    return m


def _flag(s: pd.Series) -> pd.Series:
    return s.astype("boolean")


def sample(d: pd.DataFrame, keep_xmas: bool = False) -> pd.DataFrame:
    s = panel.usable(d)
    s = s[_in_periods(s["date"])]
    if not keep_xmas:
        s = s[~panel.doy_in(s["date"], *XMAS)]
    s = s[_flag(s[TREAT]).notna()].copy()
    s["h"] = _flag(s[TREAT]).astype(float)
    pub = _flag(s["swiss_public_holiday_german_shopping_day"]).fillna(False)
    s["h_public"] = pub.astype(float)
    s["h_school_only"] = ((s["h"] == 1) & ~pub).astype(float)
    s["h_sat"] = s["h"] * s["is_saturday"]
    return s


def _fit(s: pd.DataFrame, x: list[str], cluster: str = "week", fe=FE) -> FEResult:
    return feols(s, "y", [*x, *panel.CONTROLS], fe, cluster=cluster)


def _date_flags(d: pd.DataFrame) -> pd.Series:
    """Any TG/ZH public or school holiday per calendar date (whether or not German shops open)."""
    per = d.drop_duplicates("date").set_index("date").sort_index()
    any_ch = _flag(per["ch_public_holiday"]).fillna(False) | _flag(per["ch_school_holiday"]).fillna(
        False
    )
    full = pd.date_range(per.index.min(), per.index.max(), freq="D")
    return any_ch.reindex(full, fill_value=False).astype(bool)


@dataclass
class Results:
    table: pd.DataFrame
    counts: dict


def _row(label: str, kind: str, res: FEResult, s: pd.DataFrame, coef: str = "h", **w) -> dict:
    c = res.contrast(w or {coef: 1.0})
    base = s.loc[s["h"] == 0, "y"].mean() if "h" in s else float("nan")
    return {
        "label": label,
        "kind": kind,
        **c,
        "nobs": res.nobs,
        "pct_of_mean": 100 * c["est"] / base,
        "cars": panel.cars(c["est"], s),
    }


def run(d: pd.DataFrame, bins: pd.DataFrame) -> Results:
    rows = []
    main = sample(d)
    res = _fit(main, ["h"])
    rows.append(_row("Main: any TG/ZH holiday on a German shopping day", "main", res, main))

    r1 = _fit(main, ["h_public", "h_school_only"])
    rows.append(
        _row("1a: Swiss public holiday (only 1 August, 5 days)", "split", r1, main, "h_public")
    )
    rows.append(_row("1b: Swiss school holiday only", "split", r1, main, "h_school_only"))

    r2 = _fit(main, ["h", "h_sat"])
    rows.append(_row("2a: on Mon–Fri", "split", r2, main, "h"))
    rows.append(_row("2b: on Saturdays", "split", r2, main, h=1.0, h_sat=1.0))

    s3 = main.copy()
    tg = _flag(s3["ch_tg_public_holiday"]).fillna(False) | _flag(s3["ch_tg_school_holiday"])
    zh = _flag(s3["ch_zh_public_holiday"]).fillna(False) | _flag(s3["ch_zh_school_holiday"])
    s3 = s3[tg.notna() & zh.notna()].copy()
    tg, zh = tg[s3.index].astype(bool), zh[s3.index].astype(bool)
    s3["tg_only"] = (tg & ~zh).astype(float)
    s3["zh_only"] = (zh & ~tg).astype(float)
    s3["both"] = (tg & zh).astype(float)
    r3 = _fit(s3, ["tg_only", "zh_only", "both"])
    for name, label in (
        ("tg_only", "3a: Thurgau only"),
        ("zh_only", "3b: Zürich only"),
        ("both", "3c: both cantons"),
    ):
        rows.append(_row(label, "split", r3, s3, name))

    s4 = main[main["de_school"] == 0]
    rows.append(_row("4: only days without BW school holidays", "robust", _fit(s4, ["h"]), s4))

    s5 = sample(d, keep_xmas=True)
    s5["xmas_day"] = s5["date"].dt.strftime("%m-%d").where(panel.doy_in(s5["date"], *XMAS), "none")
    r5 = _fit(s5, ["h"], fe=[*FE, "xmas_day"])
    rows.append(_row("5: keeping 20 Dec–6 Jan (day-of-season FE)", "robust", r5, s5))

    rows.append(_row("6: clustered by date", "robust", _fit(main, ["h"], cluster="date"), main))

    s7 = main.copy()
    names = []
    for g in panel.GROUP_ORDER:
        s7[f"h_{g}"] = s7["h"] * (s7["group"] == g)
        names.append(f"h_{g}")
    s7["h_other"] = s7["h"] * (~s7["group"].isin(panel.GROUP_ORDER))
    r7 = _fit(s7, [*names, "h_other"])
    labels = {"lago": "LAGO", "centre": "city centre", "less_shopping": "less shopping-oriented"}
    for g in panel.GROUP_ORDER:
        sub = s7[s7["group"] == g]
        rows.append(_row(f"7: {labels[g]}", "group", r7, sub, f"h_{g}"))

    flags = _date_flags(d)
    for shift in (-PLACEBO_SHIFT, PLACEBO_SHIFT):
        s8 = main[main["h"] == 0].copy()
        shifted = flags.shift(shift).reindex(s8["date"]).fillna(False).to_numpy()
        s8["placebo"] = shifted.astype(float)
        sign = "earlier" if shift < 0 else "later"
        rows.append(
            _row(
                f"8: placebo, Swiss dates moved {PLACEBO_SHIFT} days {sign}",
                "placebo",
                _fit(s8, ["placebo"]),
                s8,
                "placebo",
            )
        )

    keys = main[["lot_id", "date", "ym", "day_of_week", "week", "h", *panel.CONTROLS]]
    b = bins[["lot_id", "date", "hour", "y"]].merge(keys, on=["lot_id", "date"])
    r9 = feols(b, "y", ["h", *panel.CONTROLS], [*FE, ["lot_id", "hour"]], cluster="week")
    rows.append(_row("9: 15-minute level", "robust", r9, main))

    hol_dates = main.loc[main["h"] == 1, "date"].drop_duplicates()
    pub_dates = main.loc[main["h_public"] == 1, "date"].drop_duplicates()
    counts = {
        "obs": len(main),
        "dates": int(main["date"].nunique()),
        "holiday_dates": len(hol_dates),
        "public_dates": len(pub_dates),
        "public_names": sorted(
            main.loc[main["h_public"] == 1, "ch_public_holiday_name"].dropna().unique()
        )
        if "ch_public_holiday_name" in main
        else [],
        "holiday_weeks": int(main.loc[main["h"] == 1, "week"].nunique()),
        "na_dropped_dates": int(
            panel.usable(d)
            .loc[lambda x: _in_periods(x["date"]) & _flag(x[TREAT]).isna(), "date"]
            .nunique()
        ),
        "mean_y_nonholiday": float(main.loc[main["h"] == 0, "y"].mean()),
        "capacity": float(main.groupby("lot_id")["capacity"].median().sum()),
        "lots": sorted(main["lot_id"].unique()),
    }
    return Results(table=pd.DataFrame(rows), counts=counts)
