import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from konstanz_parking.analysis import panel
from konstanz_parking.analysis.fe import feols


def _panel(seed: int = 0, effect: float = 5.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for lot in range(6):
        lot_fe = rng.normal(0, 10)
        for year in range(2016, 2021):
            year_fe = rng.normal(0, 3)
            for day in range(120):
                post = int(day >= 60)
                dow = day % 6
                treat = int(year == 2020)
                x = rng.normal()
                y = lot_fe + year_fe + 4 * post + 2 * dow + effect * treat * post + 1.5 * x
                rows.append(
                    {
                        "lot": lot,
                        "year": year,
                        "post": post,
                        "dow": dow,
                        "did": treat * post,
                        "x": x,
                        "date": f"{year}-{day}",
                        "y": y + rng.normal(0, 2),
                    }
                )
    return pd.DataFrame(rows)


def test_feols_recovers_did_effect_with_absorbed_fixed_effects():
    df = _panel(effect=5.0)
    res = feols(df, "y", ["did", "x"], [["lot", "year"], ["lot", "post"], ["lot", "dow"]], "date")
    lo, hi = res.ci("did")
    assert lo < 5.0 < hi
    assert res.coef["x"] == pytest.approx(1.5, abs=0.1)


def test_feols_matches_statsmodels_dummies_and_cluster_se():
    df = _panel(seed=1)
    res = feols(df, "y", ["did", "x"], [["lot", "year"], "dow"], cluster="date")
    df["ly"] = df["lot"].astype(str) + "_" + df["year"].astype(str)
    dummies = pd.get_dummies(df[["ly", "dow"]].astype(str), drop_first=True, dtype=float)
    exog = sm.add_constant(pd.concat([df[["did", "x"]], dummies], axis=1))
    ref = sm.OLS(df["y"], exog).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(df["date"])[0]}
    )
    assert res.coef["did"] == pytest.approx(ref.params["did"], rel=1e-8)
    # Same estimator; only the degrees-of-freedom factor differs slightly.
    assert res.se["did"] == pytest.approx(ref.bse["did"], rel=0.05)


def test_contrast_of_two_coefficients():
    df = _panel(seed=2)
    res = feols(df, "y", ["did", "x"], [["lot", "year"], ["lot", "post"], "dow"], "date")
    c = res.contrast({"did": 1.0, "x": -1.0})
    assert c["est"] == pytest.approx(res.coef["did"] - res.coef["x"])
    assert c["lo"] < c["est"] < c["hi"]


def test_bridge_days():
    dates = pd.date_range("2020-05-18", "2020-05-26", freq="D")
    holiday = pd.Series(False, index=dates)
    holiday[pd.Timestamp("2020-05-21")] = True  # Ascension (Thursday)
    b = panel.bridge_days(dates, holiday)
    assert b[pd.Timestamp("2020-05-22")]  # Friday after Ascension
    assert b.sum() == 1


def test_doy_in_handles_windows_over_new_year():
    s = pd.Series(pd.to_datetime(["2019-12-19", "2019-12-20", "2020-01-06", "2020-01-07"]))
    assert panel.doy_in(s, "12-20", "01-06").tolist() == [False, True, True, False]


def test_spline_trend_basis_has_requested_degrees_of_freedom():
    from konstanz_parking.analysis.fx_effect import _spline

    m = pd.DataFrame({"t": np.linspace(0, 5, 60)})
    names = _spline(m, df=4)
    assert len(names) == 4
    assert np.isfinite(m[names].to_numpy()).all()


def test_fx_monthly_lag_uses_previous_three_months(tmp_path):
    from konstanz_parking.analysis.fx_effect import fx_monthly

    days = pd.date_range("2020-01-01", "2020-05-31", freq="D")
    rate = np.where(days.month <= 3, 1.0, 1.1)
    csv = tmp_path / "ecb.csv"
    pd.DataFrame({"TIME_PERIOD": days.strftime("%Y-%m-%d"), "OBS_VALUE": rate}).to_csv(csv)
    m = fx_monthly(csv)
    assert m.loc["2020-04", "x_lag3"] == pytest.approx(0.0)  # Jan-Mar at 1.0
    assert m.loc["2020-04", "x"] == pytest.approx(-np.log(1.1))
