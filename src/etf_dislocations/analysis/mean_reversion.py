"""Mean reversion of the premium/discount: AR(1) half-lives by regime
(SPEC.md section 2.10).

For each ETF the daily premium/discount is fit as

    pd_t = alpha + beta * pd_{t-1} + eps_t

on the full sample and separately on calm and stress subsamples (a day
belongs to the regime of its tier2_stress flag; the lagged observation is
the previous trading day regardless of that day's regime). The implied
half-life is ln(0.5)/ln(beta) trading days: 0 when beta <= 0 (reversion
within a day), infinite when beta >= 1 (no reversion).

The calm-vs-stress persistence difference is tested per ETF with a
Chow-style interaction regression

    pd_t = a + b*pd_{t-1} + c*stress_t + d*(pd_{t-1}*stress_t) + eps_t

where d is the change in AR(1) slope on stress days, with
heteroskedasticity-robust (HC1) standard errors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["date", "ticker", "bucket", "premium_discount", "tier2_stress"]

HALF_LIFE_COLUMNS = [
    "ticker", "bucket", "regime", "n", "alpha", "beta", "beta_se", "half_life",
]

REGIME_TEST_COLUMNS = [
    "ticker", "bucket", "n", "beta_calm", "beta_stress_shift",
    "beta_stress_shift_se", "tstat", "pvalue",
]


@dataclass(frozen=True)
class Ar1Fit:
    n: int
    alpha: float
    beta: float
    beta_se: float
    half_life: float


def implied_half_life(beta: float) -> float:
    """Half-life in trading days implied by an AR(1) coefficient."""
    if np.isnan(beta):
        return np.nan
    if beta <= 0.0:
        return 0.0
    if beta >= 1.0:
        return np.inf
    return float(np.log(0.5) / np.log(beta))


def fit_ar1(current: pd.Series, lagged: pd.Series) -> Ar1Fit | None:
    """OLS AR(1) fit on aligned (pd_t, pd_{t-1}) pairs; None if degenerate."""
    pairs = pd.DataFrame({"y": current, "x": lagged}).dropna()
    n = len(pairs)
    if n < 3 or pairs["x"].nunique() < 2:
        return None

    x = pairs["x"].to_numpy()
    y = pairs["y"].to_numpy()
    x_mean, y_mean = x.mean(), y.mean()
    sxx = float(((x - x_mean) ** 2).sum())
    beta = float(((x - x_mean) * (y - y_mean)).sum() / sxx)
    alpha = float(y_mean - beta * x_mean)

    resid = y - alpha - beta * x
    sigma2 = float((resid**2).sum() / (n - 2))
    beta_se = float(np.sqrt(sigma2 / sxx))

    return Ar1Fit(
        n=n, alpha=alpha, beta=beta, beta_se=beta_se,
        half_life=implied_half_life(beta),
    )


def _regime_test(sub: pd.DataFrame) -> dict | None:
    """Interaction regression testing whether the AR(1) slope shifts on
    stress days. Returns None when either regime is empty."""
    import statsmodels.api as sm

    data = pd.DataFrame(
        {
            "y": sub["premium_discount"],
            "lag": sub["premium_discount"].shift(1),
            "stress": sub["tier2_stress"].astype(float),
        }
    ).dropna()
    if data.empty or data["stress"].nunique() < 2:
        return None

    exog = pd.DataFrame(
        {
            "const": 1.0,
            "lag": data["lag"],
            "stress": data["stress"],
            "lag_x_stress": data["lag"] * data["stress"],
        }
    )
    fit = sm.OLS(data["y"], exog).fit(cov_type="HC1")
    return {
        "n": int(fit.nobs),
        "beta_calm": float(fit.params["lag"]),
        "beta_stress_shift": float(fit.params["lag_x_stress"]),
        "beta_stress_shift_se": float(fit.bse["lag_x_stress"]),
        "tstat": float(fit.tvalues["lag_x_stress"]),
        "pvalue": float(fit.pvalues["lag_x_stress"]),
    }


def run_mean_reversion(
    panel: pd.DataFrame, min_obs: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Half-life table (full/calm/stress per ETF) and regime-shift tests.

    Regime subsamples with fewer than min_obs pairs are skipped; the regime
    test is skipped for ETFs whose sample lacks one of the regimes.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in panel.columns]
    if missing:
        raise ValueError(f"Panel is missing required columns: {missing}")

    half_life_rows = []
    test_rows = []
    for ticker, sub in panel.sort_values("date").groupby("ticker", sort=True):
        sub = sub.reset_index(drop=True)
        bucket = sub["bucket"].iloc[0]
        current = sub["premium_discount"]
        lagged = current.shift(1)
        stress = sub["tier2_stress"].astype(bool)

        regimes = {
            "full": pd.Series(True, index=sub.index),
            "calm": ~stress,
            "stress": stress,
        }
        for regime, mask in regimes.items():
            fit = fit_ar1(current[mask], lagged[mask])
            if fit is None or fit.n < min_obs:
                n_pairs = 0 if fit is None else fit.n
                logger.warning(
                    "%s/%s: %d pairs (< %d), skipping", ticker, regime,
                    n_pairs, min_obs,
                )
                continue
            half_life_rows.append(
                {
                    "ticker": ticker, "bucket": bucket, "regime": regime,
                    "n": fit.n, "alpha": fit.alpha, "beta": fit.beta,
                    "beta_se": fit.beta_se, "half_life": fit.half_life,
                }
            )

        test = _regime_test(sub)
        if test is not None:
            test_rows.append({"ticker": ticker, "bucket": bucket, **test})

    if not half_life_rows:
        raise ValueError("Mean-reversion analysis produced no results")

    half_lives = pd.DataFrame(half_life_rows).loc[:, HALF_LIFE_COLUMNS]
    tests = (
        pd.DataFrame(test_rows).loc[:, REGIME_TEST_COLUMNS]
        if test_rows
        else pd.DataFrame(columns=REGIME_TEST_COLUMNS)
    )
    logger.info(
        "Mean reversion: %d half-life rows, %d regime tests",
        len(half_lives), len(tests),
    )
    return half_lives, tests
