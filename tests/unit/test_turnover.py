import math

import numpy as np
import pandas as pd
import pytest

from etf_dislocations.liquidity.turnover import abnormal_volume


def test_abnormal_volume_hand_computed():
    # Trailing window of 3 over [100, 200, 300]: mean 200, sd 100.
    vol = pd.Series([100.0, 200.0, 300.0, 400.0])
    z = abnormal_volume(vol, window=3)
    assert z.iloc[:3].isna().all()
    assert z.iloc[3] == pytest.approx((400 - 200) / 100)


def test_abnormal_volume_excludes_current_day_from_baseline():
    # A huge spike should not dampen its own z-score via the baseline.
    vol = pd.Series([100.0] * 5 + [1000.0])
    z = abnormal_volume(vol, window=5)
    # Trailing sd is zero (flat baseline) -> NaN rather than inf.
    assert math.isnan(z.iloc[5])

    vol2 = pd.Series([100.0, 110.0, 90.0, 105.0, 95.0, 1000.0])
    z2 = abnormal_volume(vol2, window=5)
    baseline = vol2.iloc[:5]
    expected = (1000 - baseline.mean()) / baseline.std(ddof=1)
    assert z2.iloc[5] == pytest.approx(expected)


def test_abnormal_volume_rejects_tiny_window():
    with pytest.raises(ValueError):
        abnormal_volume(pd.Series([1.0]), window=1)
