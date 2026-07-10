"""Panel construction: stack per-ticker daily series into one ETF-day panel.

This is the single dataset later analysis milestones consume (SPEC.md section
5.3). One row per (ticker, date); liquidity metrics are computed per ticker
before stacking so rolling windows never cross tickers.
"""

from __future__ import annotations

import logging

import pandas as pd

from .config import LiquiditySettings
from .liquidity.metrics import (
    amihud_illiquidity,
    daily_returns,
    dollar_volume,
    realized_volatility,
    rolling_mean,
)
from .universe import Universe

logger = logging.getLogger(__name__)

PANEL_COLUMNS = [
    "date",
    "ticker",
    "bucket",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "dollar_volume",
    "ret",
    "realized_vol",
    "amihud",
    "amihud_roll",
]


def build_ticker_frame(
    ticker: str,
    prices: pd.DataFrame,
    bucket: str,
    liq: LiquiditySettings,
) -> pd.DataFrame:
    """Compute liquidity metrics for one ticker's cleaned price frame."""
    out = prices.copy()
    out["dollar_volume"] = dollar_volume(out["close"], out["volume"])
    out["ret"] = daily_returns(out["close"])
    out["realized_vol"] = realized_volatility(
        out["ret"], window=liq.rolling_window,
        annualisation_days=liq.annualisation_days,
    )
    out["amihud"] = amihud_illiquidity(out["ret"], out["dollar_volume"])
    out["amihud_roll"] = rolling_mean(
        out["amihud"], window=liq.rolling_window, name="amihud_roll"
    )
    out["ticker"] = ticker
    out["bucket"] = bucket
    return out.reset_index()


def build_panel(
    prices: dict[str, pd.DataFrame],
    universe: Universe,
    liq: LiquiditySettings,
) -> pd.DataFrame:
    """Build the long ETF-day panel from cleaned per-ticker prices.

    Every ticker in `prices` must belong to the universe (its bucket tag comes
    from there). Returns a frame with PANEL_COLUMNS, sorted by (ticker, date),
    with a unique (ticker, date) key guaranteed.
    """
    if not prices:
        raise ValueError("No price data supplied")

    frames = []
    for ticker in sorted(prices):
        bucket = universe.bucket_of(ticker)  # raises if unknown
        frames.append(build_ticker_frame(ticker, prices[ticker], bucket, liq))

    panel = pd.concat(frames, ignore_index=True)
    panel = panel.loc[:, PANEL_COLUMNS].sort_values(["ticker", "date"])
    panel = panel.reset_index(drop=True)

    dups = panel.duplicated(subset=["ticker", "date"])
    if dups.any():
        raise ValueError(
            f"Panel has {int(dups.sum())} duplicate (ticker, date) rows"
        )
    logger.info(
        "Built panel: %d rows, %d tickers, %s to %s",
        len(panel),
        panel["ticker"].nunique(),
        panel["date"].min().date(),
        panel["date"].max().date(),
    )
    return panel
