"""Stale-pricing flag for international-equity ETFs (SPEC.md section 2.6).

A US trading day is flagged when the ETF's representative foreign primary
market was closed, so the official NAV is struck off stale foreign closes and
a measured premium/discount partly reflects the time-zone gap rather than
genuine dislocation. One representative calendar per fund (configured in
data_sources.yaml) is a deliberate simplification for multi-country baskets.

Calendars come from pandas_market_calendars, which computes sessions locally
(no network access).
"""

from __future__ import annotations

import functools
import logging

import pandas as pd

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _sessions(calendar_name: str, start: str, end: str) -> frozenset:
    import pandas_market_calendars as mcal

    cal = mcal.get_calendar(calendar_name)
    days = cal.valid_days(start_date=start, end_date=end)
    return frozenset(pd.DatetimeIndex(days).tz_localize(None).normalize())


def stale_pricing_flags(
    dates: pd.DatetimeIndex,
    ticker: str,
    foreign_calendars: dict[str, str],
) -> pd.Series:
    """True on dates when the ticker's foreign market was closed.

    Tickers without a configured foreign calendar (domestic funds) get all
    False: their NAV is struck off same-session prices by construction.
    """
    calendar_name = foreign_calendars.get(ticker)
    if calendar_name is None:
        return pd.Series(False, index=dates, name="stale_pricing")

    start = dates.min().date().isoformat()
    end = dates.max().date().isoformat()
    open_days = _sessions(calendar_name, start, end)
    flags = pd.Series(
        [d not in open_days for d in dates.normalize()],
        index=dates,
        name="stale_pricing",
    )
    if flags.any():
        logger.info(
            "%s: %d/%d days flagged stale (%s closed)",
            ticker,
            int(flags.sum()),
            len(flags),
            calendar_name,
        )
    return flags
