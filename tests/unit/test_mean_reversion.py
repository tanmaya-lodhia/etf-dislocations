import math

import numpy as np
import pandas as pd
import pytest

from etf_dislocations.analysis.mean_reversion import (
    fit_ar1,
    implied_half_life,
    run_mean_reversion,
)


def _ar1_series(beta, n, sigma=0.001, seed=5, mean=0.0):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = mean * (1 - beta) + beta * x[t - 1] + rng.normal(0, sigma)
    return pd.Series(x)


def test_half_life_formula():
    assert implied_half_life(0.5) == pytest.approx(1.0)
    assert implied_half_life(0.8) == pytest.approx(math.log(0.5) / math.log(0.8))
    assert implied_half_life(0.0) == 0.0
    assert implied_half_life(-0.3) == 0.0
    assert implied_half_life(1.0) == math.inf
    assert math.isnan(implied_half_life(float("nan")))


def test_fit_ar1_recovers_known_beta():
    s = _ar1_series(beta=0.8, n=5000)
    fit = fit_ar1(s, s.shift(1))
    assert fit.beta == pytest.approx(0.8, abs=0.02)
    assert fit.half_life == pytest.approx(implied_half_life(fit.beta))
    assert fit.n == 4999
    assert fit.beta_se > 0
    # True beta within a few standard errors of the estimate.
    assert abs(fit.beta - 0.8) < 4 * fit.beta_se


def test_fit_ar1_degenerate_inputs():
    constant = pd.Series([1.0] * 50)
    assert fit_ar1(constant, constant.shift(1)) is None
    short = pd.Series([1.0, 2.0])
    assert fit_ar1(short, short.shift(1)) is None


def _regime_panel(beta_calm=0.5, beta_stress=0.95, n=600, seed=9):
    """One ticker whose AR(1) persistence rises in a stress block covering
    the middle third of the sample."""
    rng = np.random.default_rng(seed)
    stress = np.zeros(n, dtype=bool)
    stress[n // 3: 2 * n // 3] = True
    x = np.zeros(n)
    for t in range(1, n):
        b = beta_stress if stress[t] else beta_calm
        x[t] = b * x[t - 1] + rng.normal(0, 0.001)
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2018-01-02", periods=n),
            "ticker": "AAA",
            "bucket": "ig_credit",
            "premium_discount": x,
            "tier2_stress": stress,
        }
    )


def test_regime_half_lives_and_shift_test():
    panel = _regime_panel()
    half_lives, tests = run_mean_reversion(panel, min_obs=30)

    hl = half_lives.set_index("regime")
    assert set(hl.index) == {"full", "calm", "stress"}
    assert hl.loc["calm", "beta"] == pytest.approx(0.5, abs=0.12)
    assert hl.loc["stress", "beta"] == pytest.approx(0.95, abs=0.04)
    assert hl.loc["stress", "half_life"] > hl.loc["calm", "half_life"]

    test = tests.iloc[0]
    assert test["beta_stress_shift"] == pytest.approx(0.45, abs=0.12)
    assert test["pvalue"] < 0.01


def test_no_persistence_difference_is_insignificant():
    panel = _regime_panel(beta_calm=0.6, beta_stress=0.6, n=2000, seed=1)
    _, tests = run_mean_reversion(panel, min_obs=30)
    assert tests.iloc[0]["pvalue"] > 0.05


def test_sparse_regime_skipped_but_others_reported():
    panel = _regime_panel(n=200)
    panel["tier2_stress"] = False
    panel.loc[panel.index[-5:], "tier2_stress"] = True  # too few stress days
    half_lives, tests = run_mean_reversion(panel, min_obs=30)
    assert set(half_lives["regime"]) == {"full", "calm"}
    assert len(tests) == 1  # interaction test still runs on the full sample


def test_missing_columns_rejected():
    panel = _regime_panel().drop(columns="tier2_stress")
    with pytest.raises(ValueError, match="tier2_stress"):
        run_mean_reversion(panel, min_obs=30)
