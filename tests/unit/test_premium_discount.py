import math

import numpy as np
import pandas as pd
import pytest

from etf_dislocations.dislocation.premium_discount import (
    log_premium_discount,
    premium_discount,
)

DATES = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])


def test_premium_discount_hand_computed():
    close = pd.Series([101.0, 99.0, 100.0], index=DATES)
    nav = pd.Series([100.0, 100.0, 100.0], index=DATES)
    pd_ = premium_discount(close, nav)
    assert pd_.iloc[0] == pytest.approx(0.01)   # 1% premium
    assert pd_.iloc[1] == pytest.approx(-0.01)  # 1% discount
    assert pd_.iloc[2] == pytest.approx(0.0)


def test_log_premium_discount_hand_computed():
    close = pd.Series([101.0], index=DATES[:1])
    nav = pd.Series([100.0], index=DATES[:1])
    lpd = log_premium_discount(close, nav)
    assert lpd.iloc[0] == pytest.approx(np.log(1.01))


def test_missing_and_nonpositive_nav_days_are_nan():
    close = pd.Series([101.0, 99.0, 100.0], index=DATES)
    nav = pd.Series([100.0, 0.0], index=DATES[:2])  # zero NAV, then absent
    pd_ = premium_discount(close, nav)
    assert pd_.iloc[0] == pytest.approx(0.01)
    assert math.isnan(pd_.iloc[1])
    assert math.isnan(pd_.iloc[2])
