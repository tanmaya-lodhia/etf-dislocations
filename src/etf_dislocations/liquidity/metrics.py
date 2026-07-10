"""Basic liquidity metrics computed from daily OHLCV.

Milestone 1 scope: dollar volume, simple daily returns, rolling realised
volatility, and the Amihud illiquidity ratio. All functions take and return
pandas Series aligned on the input index; nothing here reads files.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def dollar_volume(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Daily dollar volume: close * share volume."""
    return (close * volume).rename("dollar_volume")


def daily_returns(close: pd.Series) -> pd.Series:
    """Simple daily returns close_t / close_{t-1} - 1 (first day is NaN)."""
    return close.pct_change().rename("ret")


def realized_volatility(
    returns: pd.Series,
    window: int,
    annualisation_days: int = 252,
) -> pd.Series:
    """Rolling realised volatility: window std of daily returns, annualised.

    Uses the sample standard deviation (ddof=1) over a full window; the first
    window-1 observations are NaN.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")
    vol = returns.rolling(window, min_periods=window).std(ddof=1)
    return (vol * np.sqrt(annualisation_days)).rename("realized_vol")


def amihud_illiquidity(returns: pd.Series, dollar_vol: pd.Series) -> pd.Series:
    """Daily Amihud (2002) illiquidity ratio: |return| / dollar volume.

    Scaled by 1e6 so magnitudes are readable for liquid ETFs. Days with zero
    dollar volume yield NaN rather than inf: no trading means the price-impact
    ratio is undefined, not infinite.
    """
    dv = dollar_vol.mask(dollar_vol <= 0)
    return (returns.abs() / dv * 1e6).rename("amihud")


def rolling_mean(series: pd.Series, window: int, name: str) -> pd.Series:
    """Rolling mean over a full window (NaN until the window fills).

    Used to smooth the daily Amihud ratio per SPEC.md section 2.6.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")
    return series.rolling(window, min_periods=window).mean().rename(name)
