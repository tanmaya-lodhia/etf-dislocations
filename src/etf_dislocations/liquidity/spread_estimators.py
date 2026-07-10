"""Bid-ask spread proxies from daily OHLC (SPEC.md section 2.6).

Two estimators, chosen because both work with free daily data:

- High-low range ratio: a crude same-day proxy, 2(H-L)/(H+L).
- Corwin-Schultz (2012): infers the effective spread from the ratio of the
  two-day price range to consecutive one-day ranges, exploiting the fact that
  variance scales with time while the spread component does not.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# 3 - 2*sqrt(2), the denominator constant from Corwin and Schultz (2012).
_CS_DENOM = 3.0 - 2.0 * np.sqrt(2.0)


def high_low_spread(high: pd.Series, low: pd.Series) -> pd.Series:
    """Daily high-low range ratio: 2(H-L)/(H+L)."""
    return (2.0 * (high - low) / (high + low)).rename("hl_spread")


def corwin_schultz(high: pd.Series, low: pd.Series) -> pd.Series:
    """Corwin-Schultz (2012) high-low spread estimator, daily.

    For each consecutive day pair (t-1, t):
        beta  = ln(H_{t-1}/L_{t-1})^2 + ln(H_t/L_t)^2
        gamma = ln(max(H_{t-1}, H_t) / min(L_{t-1}, L_t))^2
        alpha = (sqrt(2*beta) - sqrt(beta)) / (3 - 2*sqrt(2))
                - sqrt(gamma / (3 - 2*sqrt(2)))
        spread = 2*(e^alpha - 1) / (1 + e^alpha)

    The value is assigned to day t; day 1 is NaN. Negative estimates are set
    to zero, the standard treatment in the original paper.
    """
    log_hl_sq = np.log(high / low) ** 2
    beta = log_hl_sq.shift(1) + log_hl_sq

    high_2d = np.maximum(high.shift(1), high)
    low_2d = np.minimum(low.shift(1), low)
    gamma = np.log(high_2d / low_2d) ** 2

    alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / _CS_DENOM - np.sqrt(
        gamma / _CS_DENOM
    )
    spread = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
    return spread.clip(lower=0.0).rename("cs_spread")
