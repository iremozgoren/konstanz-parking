"""Angle 1: the 2020 border closure as a natural experiment (difference-in-differences).

Pre-specified in ``reports/analysis_plan.md``. ``pre`` = 20 Apr-14 Jun (BW shops open, crossing to
shop banned), ``post`` = 15 Jun-9 Aug (border open). Baseline = the same calendar dates in
2016-2019. Main estimate = coefficient on ``2020 x post``, all car parks, daily level.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from konstanz_parking.analysis import panel
from konstanz_parking.analysis.fe import FEResult, feols

BASELINE = (2016, 2017, 2018, 2019)
PRE = ("04-20", "06-14")
POST = ("06-15", "08-09")
REOPEN = pd.Timestamp("2020-06-15")
ES_START, ES_END = "03-30", "08-30"  # event study: bins -11..10 around 15 June
ES_REF = -1
EXPLORE_START = "02-03"  # exploratory long event study: shows the pre-COVID level of 2020
TREND_BINS = range(-8, 0)  # 20 Apr - 14 Jun

FE_DAILY = [["lot_id", "year"], ["lot_id", "post"], ["lot_id", "day_of_week"]]

CONFOUNDER_DATES = {
    "BW mask mandate in shops": "2020-04-27",
    "BW 800 m² limit lifted": "2020-05-04",
    "Swiss shops reopen": "2020-05-11",
    "Partners/relatives may cross": "2020-05-16",
    "Border reopens": "2020-06-15",
    "German VAT cut (19→16 %)": "2020-07-01",
}


def sample(
    d: pd.DataFrame,
    baseline: tuple[int, ...] = BASELINE,
    pre: tuple[str, str] = PRE,
    post: tuple[str, str] = POST,
) -> pd.DataFrame:
    s = panel.usable(d)
    s = s[s["year"].isin((*baseline, 2020))]
    in_pre = panel.doy_in(s["date"], *pre)
    in_post = panel.doy_in(s["date"], *post)
    s = s[in_pre | in_post].copy()
    s["post"] = panel.doy_in(s["date"], *post).astype(int)
    s["treat"] = (s["year"] == 2020).astype(int)
    s["did"] = s["treat"] * s["post"]
    # A lot needs both periods in both 2020 and the baseline to identify anything.
    cells = s.groupby(["lot_id", "treat"])["post"].nunique().unstack()
    keep = cells[(cells == 2).all(axis=1)].index
    return s[s["lot_id"].isin(keep)].copy()


def did(s: pd.DataFrame) -> FEResult:
    return feols(s, "y", ["did", *panel.CONTROLS], FE_DAILY, cluster="date")


def did_groups(s: pd.DataFrame) -> FEResult:
    s = s.copy()
    names = []
    for g in panel.GROUP_ORDER:
        name = f"did_{g}"
        s[name] = s["did"] * (s["group"] == g)
        names.append(name)
    return feols(s, "y", [*names, *panel.CONTROLS], FE_DAILY, cluster="date")


def did_15min(bins: pd.DataFrame, s: pd.DataFrame) -> FEResult:
    keys = s[["lot_id", "date", "post", "did", "day_of_week", *panel.CONTROLS]]
    b = bins[["lot_id", "date", "hour", "y"]].merge(keys, on=["lot_id", "date"])
    b["year"] = b["date"].dt.year
    fe = [["lot_id", "year", "hour"], ["lot_id", "post"], ["lot_id", "day_of_week"]]
    return feols(b, "y", ["did", *panel.CONTROLS], fe, cluster="date")


@dataclass
class Results:
    variants: pd.DataFrame
    groups: pd.DataFrame
    event: pd.DataFrame
    jump: dict
    raw_weekly: pd.DataFrame
    event_long: pd.DataFrame
    by_group: dict
    lago_dates: dict = field(default_factory=dict)
    n: dict = field(default_factory=dict)
    capacity: dict = field(default_factory=dict)


def _row(name: str, kind: str, res: FEResult, s: pd.DataFrame, coef: str = "did") -> dict:
    r = res.row(coef)
    return {
        "variant": name,
        "kind": kind,
        **r,
        "n_lots": s["lot_id"].nunique(),
        "n_days_2020": int(s.loc[s["treat"] == 1, "date"].nunique()),
        "cars": panel.cars(r["est"], s),
    }


def event_study(
    d: pd.DataFrame,
    baseline: tuple[int, ...] = BASELINE,
    start: str = ES_START,
    lots: list[str] | None = None,
) -> tuple[pd.DataFrame, dict]:
    s = panel.usable(d)
    s = s[s["year"].isin((*baseline, 2020)) & panel.doy_in(s["date"], start, ES_END)].copy()
    if lots is not None:
        s = s[s["lot_id"].isin(lots)]
    reopen = pd.to_datetime(s["year"].astype(str) + "-06-15")
    s["bin"] = ((s["date"] - reopen).dt.days // 7).astype(int)
    keep = s[s["year"] != 2020]["lot_id"].unique()
    s = s[s["lot_id"].isin(keep)]
    bins = sorted(s["bin"].unique())
    # Weeks without any 2020 observation (e.g. LAGO's frozen sensor) get no dummy: their
    # coefficient is not identified and must not enter the trend fit as a fake zero.
    has_2020 = set(s.loc[s["year"] == 2020, "bin"])
    if ES_REF not in has_2020:
        raise ValueError("reference week has no 2020 data")
    names = []
    for k in bins:
        if k == ES_REF or k not in has_2020:
            continue
        name = f"es_{k}"
        s[name] = ((s["year"] == 2020) & (s["bin"] == k)).astype(float)
        names.append(name)
    fe = [["lot_id", "year"], ["lot_id", "bin"], ["lot_id", "day_of_week"]]
    res = feols(s, "y", [*names, *panel.CONTROLS], fe, cluster="date")

    rows = []
    for k in bins:
        start = REOPEN + pd.Timedelta(days=7 * k)
        if k == ES_REF:
            rows.append({"bin": k, "start": start, "est": 0.0, "lo": 0.0, "hi": 0.0, "se": 0.0})
            continue
        if k not in has_2020:
            rows.append({"bin": k, "start": start, "est": np.nan, "lo": np.nan, "hi": np.nan})
            continue
        c = res.contrast({f"es_{k}": 1.0})
        rows.append({"bin": k, "start": start, **c})
    ev = pd.DataFrame(rows)

    # Jump test: week-0 coefficient minus a linear trend through bins -8..-1, extrapolated to 0.
    trend_bins = [k for k in TREND_BINS if k in has_2020]
    ks = np.array(trend_bins, dtype=float)
    design = np.column_stack([np.ones_like(ks), ks])
    pred_w = np.array([1.0, 0.0]) @ np.linalg.pinv(design)  # weights: prediction at k = 0
    weights = {"es_0": 1.0}
    for k, w in zip(trend_bins, pred_w, strict=True):
        if k != ES_REF:
            weights[f"es_{k}"] = weights.get(f"es_{k}", 0.0) - w
    jump = res.contrast(weights)
    slope_w = np.array([0.0, 1.0]) @ np.linalg.pinv(design)
    slope = res.contrast(
        {f"es_{k}": w for k, w in zip(trend_bins, slope_w, strict=True) if k != ES_REF}
    )

    # Sensitivity of the jump to the trend's shape (added after seeing the raw series, see report):
    # linear trend through the last four weeks only, and a quadratic trend through all eight.
    def _jump(ks_: list[int], degree: int) -> dict:
        k_arr = np.array(ks_, dtype=float)
        dm = np.column_stack([k_arr**p for p in range(degree + 1)])
        w_pred = np.eye(degree + 1)[0] @ np.linalg.pinv(dm)
        ww = {"es_0": 1.0}
        for k_, w_ in zip(ks_, w_pred, strict=True):
            if k_ != ES_REF:
                ww[f"es_{k_}"] = ww.get(f"es_{k_}", 0.0) - w_
        return res.contrast(ww)

    jump_last4 = _jump([k for k in trend_bins if k >= -4], 1)
    jump_quad = _jump(trend_bins, 2)
    week0 = res.contrast({"es_0": 1.0})
    trend_pred = {"est": week0["est"] - jump["est"]}
    # Average post-reopening coefficient (weeks 0..7) for comparison with the DiD.
    post_bins = [k for k in range(0, 8) if k in has_2020]
    post_avg = res.contrast({f"es_{k}": 1 / len(post_bins) for k in post_bins})
    return ev, {
        "jump": jump,
        "slope_per_week": slope,
        "week0": week0,
        "trend_pred_week0": trend_pred,
        "post_avg_w0_7": post_avg,
        "nobs": res.nobs,
        "trend_bins": trend_bins,
        "jump_last4": jump_last4,
        "jump_quad": jump_quad,
    }


def raw_weekly(d: pd.DataFrame) -> pd.DataFrame:
    """Mean occupancy per group and week (2020 vs 2016-2019), lot-balanced, for the figure."""
    s = panel.usable(d)
    s = s[s["year"].isin((*BASELINE, 2020)) & panel.doy_in(s["date"], EXPLORE_START, "08-30")]
    s = s[s["group"].isin(panel.GROUP_ORDER)].copy()
    reopen = pd.to_datetime(s["year"].astype(str) + "-06-15")
    s["bin"] = ((s["date"] - reopen).dt.days // 7).astype(int)
    s["period"] = np.where(s["year"] == 2020, "2020", "2016–2019")
    per_lot = s.groupby(["group", "lot_id", "period", "bin"])["y"].mean().reset_index()
    out = per_lot.groupby(["group", "period", "bin"])["y"].mean().reset_index()
    out["start"] = REOPEN + pd.to_timedelta(out["bin"] * 7, unit="D")
    return out


def run(d: pd.DataFrame, bins: pd.DataFrame) -> Results:
    rows = []
    main = sample(d)
    rows.append(_row("Main: all car parks, LAGO's invalid days dropped", "main", did(main), main))

    no_lago = main[main["lot_id"] != "lago"]
    rows.append(_row("(b) Without LAGO", "lago", did(no_lago), no_lago))

    lago_dates = set(main.loc[main["lot_id"] == "lago", "date"])
    only = main[main["date"].isin(lago_dates)]
    rows.append(_row("(c) Only dates where LAGO is valid", "lago", did(only), only))

    late = sample(d, pre=("05-11", "06-14"))
    rows.append(_row("R1: pre = 11 May–14 Jun (all shops open)", "robust", did(late), late))

    b22 = sample(d, baseline=(2022,))
    rows.append(_row("R2: baseline 2022 instead of 2016–2019", "robust", did(b22), b22))

    rows.append(_row("R3: 15-minute level", "robust", did_15min(bins, main), main))

    sat = main[main["is_saturday"]]
    rows.append(_row("R4: Saturdays only", "robust", did(sat), sat))
    variants = pd.DataFrame(rows)

    gres = did_groups(main)
    grows = []
    for g in panel.GROUP_ORDER:
        sub = main[main["group"] == g]
        grows.append(
            {
                "term": g,
                **gres.contrast({f"did_{g}": 1.0}),
                "cars": None,
                "lots": ", ".join(sorted(sub["lot_id"].unique())),
            }
        )
        grows[-1]["cars"] = panel.cars(grows[-1]["est"], sub)
    for g in ("lago", "centre"):
        grows.append(
            {
                "term": f"{g} − less_shopping",
                **gres.contrast({f"did_{g}": 1.0, "did_less_shopping": -1.0}),
                "cars": None,
                "lots": "",
            }
        )
    groups = pd.DataFrame(grows)

    event, jump = event_study(d)
    # Exploratory (not pre-specified): longer window from 3 Feb to show the pre-COVID 2020 level,
    # and the event study per car park group.
    event_long, _ = event_study(d, start=EXPLORE_START)
    by_group = {}
    for g in panel.GROUP_ORDER:
        lots = sorted(main.loc[main["group"] == g, "lot_id"].unique())
        by_group[g] = event_study(d, lots=lots)
    lago_2020 = main[(main["lot_id"] == "lago") & (main["treat"] == 1)]
    return Results(
        variants=variants,
        groups=groups,
        event=event,
        jump=jump,
        raw_weekly=raw_weekly(d),
        event_long=event_long,
        by_group=by_group,
        capacity=main.groupby("lot_id")["capacity"].median().to_dict(),
        lago_dates={
            "pre_days": int((lago_2020["post"] == 0).sum()),
            "post_days": int((lago_2020["post"] == 1).sum()),
        },
        n={
            "obs": len(main),
            "lots": sorted(main["lot_id"].unique()),
            "days_2020_pre": int(
                main.loc[(main["treat"] == 1) & (main["post"] == 0), "date"].nunique()
            ),
            "days_2020_post": int(
                main.loc[(main["treat"] == 1) & (main["post"] == 1), "date"].nunique()
            ),
            "baseline_lot_days": int((main["treat"] == 0).sum()),
            "mean_y_2020_pre": float(
                main.loc[(main["treat"] == 1) & (main["post"] == 0), "y"].mean()
            ),
        },
    )
