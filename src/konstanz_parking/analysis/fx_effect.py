"""Angle 3: CHF/EUR and occupancy (correlational), monthly panel 2015-07 to 2020-02.

Pre-specified in ``reports/analysis_plan.md``. Regressor = log(EUR per CHF), higher = stronger
franc; effects are reported per 10 % stronger franc. Main model: car park FE, calendar-month FE,
car-park-specific linear trends, weather, share of BW school holiday days and of Swiss holiday
shopping days. Driscoll-Kraay standard errors (6 monthly lags).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import BSpline

from konstanz_parking.analysis import panel
from konstanz_parking.analysis.fe import FEResult, demean, feols
from konstanz_parking.auxiliary.fx import load_fx

MAIN_PERIOD = ("2015-07", "2020-02")
EXTRA_2022 = ("2022-04", "2022-12")
MIN_DAYS = 10
DK_LAGS = 6
PER_10PCT = float(np.log(1.1))
MONTH_CONTROLS = ["temp_c", "temp_c2", "precip_mm", "sunshine_min", "de_school", "swiss_hol"]


def fx_monthly(ecb_csv: Path) -> pd.DataFrame:
    s = load_fx(ecb_csv)
    m = s.groupby(s.index.to_period("M")).mean().rename("chf_per_eur").to_frame()
    m["x"] = -np.log(m["chf_per_eur"])
    m["x_lag3"] = m["x"].shift(1).rolling(3).mean()
    m.index = m.index.astype(str)
    return m


def monthly(d: pd.DataFrame, fx: pd.DataFrame) -> pd.DataFrame:
    s = panel.usable(d).copy()
    s["swiss_hol"] = s["swiss_holiday_german_shopping_day"].astype("Float64")
    g = s.groupby(["lot_id", "ym"])
    m = g.agg(
        y=("y", "mean"),
        n_days=("y", "size"),
        capacity=("capacity", "median"),
        temp_c=("temp_c", "mean"),
        temp_c2=("temp_c2", "mean"),
        precip_mm=("precip_mm", "mean"),
        sunshine_min=("sunshine_min", "mean"),
        de_school=("de_school", "mean"),
        swiss_hol=("swiss_hol", "mean"),
    ).reset_index()
    m["swiss_hol"] = m["swiss_hol"].astype(float).fillna(0.0)
    m = m[m["n_days"] >= MIN_DAYS].merge(fx, left_on="ym", right_index=True, how="left")
    per = pd.PeriodIndex(m["ym"], freq="M")
    m["month"] = per.month
    m["year"] = per.year
    m["t"] = (per.year - 2015) + (per.month - 1) / 12
    m["tidx"] = per.year * 12 + per.month
    return m


def _period(m: pd.DataFrame, *periods: tuple[str, str]) -> pd.DataFrame:
    mask = pd.Series(False, index=m.index)
    for a, b in periods:
        mask |= (m["ym"] >= a) & (m["ym"] <= b)
    return m[mask].copy()


def _lot_trends(m: pd.DataFrame) -> list[str]:
    names = []
    for lot in sorted(m["lot_id"].unique()):
        name = f"trend_{lot}"
        m[name] = m["t"] * (m["lot_id"] == lot)
        names.append(name)
    return names


def _spline(m: pd.DataFrame, df: int = 4, degree: int = 3) -> list[str]:
    t = m["t"].to_numpy(float)
    n_inner = df - degree
    inner = np.quantile(t, np.linspace(0, 1, n_inner + 2)[1:-1])
    knots = np.r_[[t.min()] * (degree + 1), inner, [t.max()] * (degree + 1)]
    basis = BSpline.design_matrix(np.clip(t, t.min(), t.max()), knots, degree).toarray()
    names = []
    for j in range(1, basis.shape[1]):  # drop one column: collinear with the car park FE
        name = f"spline_{j}"
        m[name] = basis[:, j]
        names.append(name)
    return names


FE = ["lot_id", "month"]


def fit(m: pd.DataFrame, trend: str = "lot_linear", xcol: str = "x") -> tuple[FEResult, list[str]]:
    m = m.copy()
    if trend == "lot_linear":
        tr = _lot_trends(m)
    elif trend == "quadratic":
        m["t2"] = m["t"] ** 2
        tr = ["t", "t2"]
    elif trend == "spline":
        tr = _spline(m)
    elif trend == "none":
        tr = []
    else:
        raise ValueError(trend)
    res = feols(m, "y", [xcol, *MONTH_CONTROLS, *tr], FE, dk_time="tidx", dk_lags=DK_LAGS)
    return res, tr


def partial_residuals(m: pd.DataFrame) -> pd.DataFrame:
    """Frisch-Waugh-Lovell: y and x net of fixed effects, controls and lot trends (main model)."""
    m = m.copy()
    tr = _lot_trends(m)
    ctrl = [*MONTH_CONTROLS, *tr]
    groups = [pd.factorize(m[c])[0] for c in FE]
    mat = demean(m[["y", "x", *ctrl]].to_numpy(float), groups)
    z = mat[:, 2:]
    proj = z @ np.linalg.pinv(z)
    out = m[["lot_id", "ym"]].copy()
    out["y_res"] = mat[:, 0] - proj @ mat[:, 0]
    out["x_res"] = mat[:, 1] - proj @ mat[:, 1]
    # Share of the FX variation (within car park) that is left after the controls.
    x_within = demean(m[["x"]].to_numpy(float), [groups[0]])[:, 0]
    out.attrs["x_share_left"] = float(out["x_res"].var() / x_within.var())
    return out


@dataclass
class Results:
    table: pd.DataFrame
    resid: pd.DataFrame
    fx: pd.DataFrame
    counts: dict


def _row(label: str, kind: str, res: FEResult, m: pd.DataFrame, xcol: str = "x") -> dict:
    c = res.contrast({xcol: PER_10PCT})
    return {
        "label": label,
        "kind": kind,
        **c,
        "nobs": res.nobs,
        "months": int(m.dropna(subset=[xcol])["ym"].nunique()),
        "cars": panel.cars(c["est"], m),
    }


def run(d: pd.DataFrame, ecb_csv: Path) -> Results:
    fx = fx_monthly(ecb_csv)
    m_all = monthly(d, fx)
    main = _period(m_all, MAIN_PERIOD)
    rows = [
        _row("Main: car-park linear trends", "main", fit(main)[0], main),
        _row("1: no trend", "robust", fit(main, "none")[0], main),
        _row("2: common quadratic trend", "robust", fit(main, "quadratic")[0], main),
        _row("3: spline trend (4 df)", "robust", fit(main, "spline")[0], main),
        _row(
            "4: FX lagged (mean of previous 3 months)",
            "robust",
            fit(main, xcol="x_lag3")[0],
            main,
            "x_lag3",
        ),
    ]
    no15 = main[main["year"] > 2015]
    rows.append(_row("5: excluding 2015", "robust", fit(no15)[0], no15))
    with22 = _period(m_all, MAIN_PERIOD, EXTRA_2022)
    rows.append(_row("6: including Apr–Dec 2022", "robust", fit(with22)[0], with22))

    resid = partial_residuals(main)
    fx_range = fx.loc[MAIN_PERIOD[0] : MAIN_PERIOD[1], "chf_per_eur"]
    counts = {
        "obs": len(main),
        "months": int(main["ym"].nunique()),
        "lots": sorted(main["lot_id"].unique()),
        "fx_min": float(fx_range.min()),
        "fx_max": float(fx_range.max()),
        "fx_min_month": str(fx_range.idxmin()),
        "fx_max_month": str(fx_range.idxmax()),
        "x_share_left": resid.attrs["x_share_left"],
        "mean_y": float(main["y"].mean()),
    }
    return Results(table=pd.DataFrame(rows), resid=resid, fx=fx, counts=counts)
