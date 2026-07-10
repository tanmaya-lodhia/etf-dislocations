"""ETF trading-pressure proxy: abnormal volume (SPEC.md section 2.6).

Shares outstanding are not reliably available from free sources, so the
demand-pressure proxy is a z-score of share volume against its own trailing
baseline rather than true turnover. The window excludes the current day so a
spike does not inflate its own baseline.
"""

from __future__ import annotations

import pandas as pd


def abnormal_volume(volume: pd.Series, window: int) -> pd.Series:
    """Volume z-score vs. the trailing `window` days (excluding today).

    NaN until the trailing window is full; NaN when the trailing standard
    deviation is zero (a flat baseline has no meaningful z-score).
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")
    trailing = volume.shift(1).rolling(window, min_periods=window)
    mean = trailing.mean()
    std = trailing.std(ddof=1)
    z = (volume - mean) / std.mask(std == 0)
    return z.rename("abnormal_volume")
