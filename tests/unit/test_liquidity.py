import math

import numpy as np
import pandas as pd
import pytest

from etf_dislocations.liquidity.metrics import (
    amihud_illiquidity,
    daily_returns,
    dollar_volume,
    realized_volatility,
    rolling_mean,
)


def test_dollar_volume_hand_computed():
    close = pd.Series([10.0, 20.0, 5.0])
    volume = pd.Series([100.0, 50.0, 0.0])
    dv = dollar_volume(close, volume)
    assert dv.tolist() == [1000.0, 1000.0, 0.0]


def test_daily_returns_hand_computed():
    close = pd.Series([100.0, 110.0, 99.0])
    ret = daily_returns(close)
    assert math.isnan(ret.iloc[0])
    assert ret.iloc[1] == pytest.approx(0.10)
    assert ret.iloc[2] == pytest.approx(-0.10)


def test_realized_volatility_hand_computed():
    # Returns [0.01, -0.01, 0.01]: sample std over window 3 is 0.011547...
    ret = pd.Series([np.nan, 0.01, -0.01, 0.01])
    vol = realized_volatility(ret, window=3, annualisation_days=252)
    expected = np.std([0.01, -0.01, 0.01], ddof=1) * np.sqrt(252)
    assert math.isnan(vol.iloc[2])  # window not yet full of valid returns
    assert vol.iloc[3] == pytest.approx(expected)


def test_realized_volatility_rejects_tiny_window():
    with pytest.raises(ValueError):
        realized_volatility(pd.Series([0.01]), window=1)


def test_amihud_hand_computed():
    ret = pd.Series([np.nan, 0.02, -0.01])
    dv = pd.Series([1e6, 2e6, 1e6])
    am = amihud_illiquidity(ret, dv)
    assert math.isnan(am.iloc[0])
    assert am.iloc[1] == pytest.approx(0.02 / 2e6 * 1e6)  # = 0.01
    assert am.iloc[2] == pytest.approx(0.01 / 1e6 * 1e6)  # = 0.01


def test_amihud_zero_volume_is_nan_not_inf():
    ret = pd.Series([0.05])
    dv = pd.Series([0.0])
    am = amihud_illiquidity(ret, dv)
    assert math.isnan(am.iloc[0])


def test_rolling_mean_full_window_only():
    s = pd.Series([1.0, 2.0, 3.0, 4.0])
    rm = rolling_mean(s, window=3, name="rm")
    assert math.isnan(rm.iloc[1])
    assert rm.iloc[2] == pytest.approx(2.0)
    assert rm.iloc[3] == pytest.approx(3.0)
