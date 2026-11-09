"""Small OLS estimator with absorbed fixed effects and robust standard errors.

Fixed effects are removed by alternating projections (iterated group demeaning), so models with
hundreds of fixed-effect levels and ~10^5-10^6 rows stay cheap. Supported covariances:

- ``cluster``: one-way cluster-robust (CR1), small-sample factor G/(G-1) * (N-1)/(N-K).
- ``dk_time``: Driscoll-Kraay (scores summed per time period, Bartlett kernel), for panels with
  cross-sectional and serial correlation.

K counts the regressors plus all fixed-effect levels (slightly conservative).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

TOL = 1e-10
MAX_ITER = 5000


@dataclass
class FEResult:
    coef: pd.Series
    cov: pd.DataFrame
    nobs: int
    n_clusters: int | None
    dof: int

    @property
    def se(self) -> pd.Series:
        return pd.Series(np.sqrt(np.diag(self.cov.values)), index=self.coef.index)

    def ci(self, name: str, level: float = 0.95) -> tuple[float, float]:
        z = self._crit(level)
        return self.coef[name] - z * self.se[name], self.coef[name] + z * self.se[name]

    def _crit(self, level: float) -> float:
        df = (self.n_clusters - 1) if self.n_clusters else self.dof
        return float(stats.t.ppf(0.5 + level / 2, df))

    def contrast(self, weights: dict[str, float], level: float = 0.95) -> dict[str, float]:
        """Estimate, SE, CI and p-value of a linear combination of coefficients."""
        w = pd.Series(weights).reindex(self.coef.index, fill_value=0.0)
        est = float(w @ self.coef)
        se = float(np.sqrt(w.values @ self.cov.values @ w.values))
        z = self._crit(level)
        df = (self.n_clusters - 1) if self.n_clusters else self.dof
        p = float(2 * stats.t.sf(abs(est / se), df)) if se > 0 else float("nan")
        return {"est": est, "se": se, "lo": est - z * se, "hi": est + z * se, "p": p}

    def row(self, name: str) -> dict[str, float]:
        return self.contrast({name: 1.0}) | {"nobs": self.nobs}


def _codes(df: pd.DataFrame, spec: str | list[str]) -> np.ndarray:
    cols = [spec] if isinstance(spec, str) else spec
    if len(cols) == 1:
        return pd.factorize(df[cols[0]], use_na_sentinel=False)[0]
    return df.groupby(cols, sort=False, observed=True).ngroup().to_numpy()


def demean(mat: np.ndarray, groups: list[np.ndarray]) -> np.ndarray:
    """Project out all fixed effects (alternating projections on every column at once)."""
    out = mat.astype(float, copy=True)
    if not groups:
        return out
    counts = [np.bincount(g) for g in groups]
    for _ in range(MAX_ITER):
        delta = 0.0
        for g, c in zip(groups, counts, strict=True):
            means = np.vstack([np.bincount(g, weights=out[:, j]) / c for j in range(out.shape[1])])
            step = means[:, g].T
            out -= step
            delta = max(delta, float(np.abs(step).max()))
        if delta < TOL or len(groups) == 1:
            return out
    raise RuntimeError("fixed-effect demeaning did not converge")


def feols(
    df: pd.DataFrame,
    y: str,
    x: list[str],
    fe: list[str | list[str]] = (),
    cluster: str | None = None,
    dk_time: str | None = None,
    dk_lags: int = 6,
) -> FEResult:
    """OLS of ``y`` on ``x`` with absorbed fixed effects ``fe`` (each a column or column list)."""
    cols = [y, *x]
    extra = [c for spec in fe for c in ([spec] if isinstance(spec, str) else spec)]
    extra += [c for c in (cluster, dk_time) if c]
    d = df.dropna(subset=list(dict.fromkeys(cols + extra))).reset_index(drop=True)
    groups = [_codes(d, spec) for spec in fe]
    mat = demean(d[cols].to_numpy(dtype=float), groups)
    yt, xt = mat[:, 0], mat[:, 1:]

    n = len(d)
    k = len(x) + sum(int(g.max()) + 1 for g in groups) - max(len(groups) - 1, 0)
    xtx_inv = np.linalg.pinv(xt.T @ xt)
    beta = xtx_inv @ xt.T @ yt
    resid = yt - xt @ beta
    scores = xt * resid[:, None]

    n_clusters = None
    if cluster:
        cl = _codes(d, cluster)
        n_clusters = int(cl.max()) + 1
        s = np.vstack([np.bincount(cl, weights=scores[:, j]) for j in range(scores.shape[1])]).T
        meat = s.T @ s
        meat *= n_clusters / (n_clusters - 1) * (n - 1) / (n - k)
    elif dk_time:
        t = _codes(d, dk_time)
        order = np.argsort(d[dk_time].to_numpy()[np.unique(t, return_index=True)[1]])
        s = np.vstack([np.bincount(t, weights=scores[:, j]) for j in range(scores.shape[1])]).T
        s = s[order]
        meat = s.T @ s
        for lag in range(1, dk_lags + 1):
            w = 1 - lag / (dk_lags + 1)
            g = s[lag:].T @ s[:-lag]
            meat += w * (g + g.T)
        meat *= (n - 1) / (n - k)
    else:
        meat = scores.T @ scores * n / (n - k)
    cov = xtx_inv @ meat @ xtx_inv
    return FEResult(
        coef=pd.Series(beta, index=x),
        cov=pd.DataFrame(cov, index=x, columns=x),
        nobs=n,
        n_clusters=n_clusters,
        dof=n - k,
    )
