"""Panel construction: stack per-ticker daily series into one ETF-day panel.

This is the single dataset later analysis milestones consume (SPEC.md section
5.3). One row per (ticker, date); all rolling measures are computed per
ticker before stacking so windows never cross tickers. NAV, stale-pricing
flags, and the VIX level are optional joins: when absent the columns exist
but are NaN (or False for the stale flag), keeping the schema stable across
data modes.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .config import LiquiditySettings
from .dislocation.premium_discount import log_premium_discount, premium_discount
from .dislocation.stale_pricing import stale_pricing_flags
from .liquidity.metrics import (
    amihud_illiquidity,
    daily_returns,
    dollar_volume,
    realized_volatility,
    rolling_mean,
)
from .liquidity.spread_estimators import corwin_schultz, high_low_spread
from .liquidity.turnover import abnormal_volume
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
    "nav",
    "premium_discount",
    "log_premium_discount",
    "dollar_volume",
    "ret",
    "realized_vol",
    "amihud",
    "amihud_roll",
    "cs_spread",
    "hl_spread",
    "abnormal_volume",
    "stale_pricing",
    "vix",
]


def build_ticker_frame(
    ticker: str,
    prices: pd.DataFrame,
    bucket: str,
    liq: LiquiditySettings,
    nav: pd.Series | None = None,
    foreign_calendars: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Compute dislocation and liquidity measures for one ticker."""
    out = prices.copy()

    if nav is not None:
        out["nav"] = nav.reindex(out.index)
        missing = int(out["nav"].isna().sum())
        if missing:
            logger.warning(
                "%s: %d/%d price dates have no NAV observation",
                ticker,
                missing,
                len(out),
            )
        out["premium_discount"] = premium_discount(out["close"], nav)
        out["log_premium_discount"] = log_premium_discount(out["close"], nav)
    else:
        out["nav"] = np.nan
        out["premium_discount"] = np.nan
        out["log_premium_discount"] = np.nan

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
    out["cs_spread"] = corwin_schultz(out["high"], out["low"])
    out["hl_spread"] = high_low_spread(out["high"], out["low"])
    out["abnormal_volume"] = abnormal_volume(out["volume"], liq.volume_window)
    out["stale_pricing"] = stale_pricing_flags(
        out.index, ticker, foreign_calendars or {}
    )
    out["ticker"] = ticker
    out["bucket"] = bucket
    return out.reset_index()


def build_panel(
    prices: dict[str, pd.DataFrame],
    universe: Universe,
    liq: LiquiditySettings,
    nav: dict[str, pd.Series] | None = None,
    vix: pd.Series | None = None,
    foreign_calendars: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Build the long ETF-day panel from cleaned per-ticker prices.

    Every ticker in `prices` must belong to the universe (its bucket tag comes
    from there). NAV series are matched by ticker where supplied. Returns a
    frame with PANEL_COLUMNS, sorted by (ticker, date), with a unique
    (ticker, date) key guaranteed.
    """
    if not prices:
        raise ValueError("No price data supplied")
    nav = nav or {}

    frames = []
    for ticker in sorted(prices):
        bucket = universe.bucket_of(ticker)  # raises if unknown
        frames.append(
            build_ticker_frame(
                ticker,
                prices[ticker],
                bucket,
                liq,
                nav=nav.get(ticker),
                foreign_calendars=foreign_calendars,
            )
        )

    panel = pd.concat(frames, ignore_index=True)
    if vix is not None:
        panel = panel.merge(
            vix.rename("vix").reset_index().rename(columns={"index": "date"}),
            on="date",
            how="left",
        )
    else:
        panel["vix"] = np.nan

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
