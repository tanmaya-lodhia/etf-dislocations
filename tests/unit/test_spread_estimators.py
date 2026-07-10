import math

import numpy as np
import pandas as pd
import pytest

from etf_dislocations.liquidity.spread_estimators import (
    corwin_schultz,
    high_low_spread,
)


def test_high_low_spread_hand_computed():
    high = pd.Series([10.5, 10.2])
    low = pd.Series([9.5, 9.8])
    s = high_low_spread(high, low)
    assert s.iloc[0] == pytest.approx(2 * 1.0 / 20.0)  # 10%
    assert s.iloc[1] == pytest.approx(2 * 0.4 / 20.0)  # 4%


def test_corwin_schultz_worked_example():
    # Two-day example computed step by step from the published formula.
    high = pd.Series([102.0, 103.0])
    low = pd.Series([99.0, 100.0])

    b = np.log(102 / 99) ** 2 + np.log(103 / 100) ** 2
    g = np.log(103 / 99) ** 2
    denom = 3 - 2 * np.sqrt(2)
    a = (np.sqrt(2 * b) - np.sqrt(b)) / denom - np.sqrt(g / denom)
    expected = max(0.0, 2 * (np.exp(a) - 1) / (1 + np.exp(a)))

    s = corwin_schultz(high, low)
    assert math.isnan(s.iloc[0])  # needs a prior day
    assert s.iloc[1] == pytest.approx(expected)


def test_corwin_schultz_negative_estimates_clamped_to_zero():
    # A large two-day range relative to the one-day ranges drives alpha
    # negative; the estimator should floor at zero, not go negative.
    high = pd.Series([100.5, 110.0])
    low = pd.Series([99.5, 109.0])
    s = corwin_schultz(high, low)
    assert s.iloc[1] == 0.0


def test_corwin_schultz_zero_range_days():
    # H == L on both days: no range information, spread estimate is 0.
    high = pd.Series([100.0, 100.0])
    low = pd.Series([100.0, 100.0])
    s = corwin_schultz(high, low)
    assert s.iloc[1] == 0.0
