"""Loading and cleaning of daily ETF price data.

Milestone 1 implements the offline fixture source only. Later milestones add
public-data ingestion behind the same interface: a loader returns a mapping
{ticker -> cleaned daily OHLCV DataFrame} and everything downstream is
source-agnostic.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def clean_prices(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Validate and clean a raw daily OHLCV frame for one ticker.

    Returns a frame indexed by normalised DatetimeIndex named 'date', sorted
    ascending, with float price columns and float volume. Rows with
    non-positive prices or negative volume are dropped with a warning;
    duplicate dates keep the last observation.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{ticker}: missing required columns {missing}")

    out = df.loc[:, REQUIRED_COLUMNS].copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    n_before = len(out)
    price_cols = ["open", "high", "low", "close"]
    bad = (
        out[price_cols].le(0).any(axis=1)
        | out[price_cols].isna().any(axis=1)
        | out["volume"].lt(0)
        | out["volume"].isna()
    )
    if bad.any():
        logger.warning(
            "%s: dropping %d/%d rows with invalid prices or volume",
            ticker,
            int(bad.sum()),
            n_before,
        )
        out = out.loc[~bad]

    out = out.sort_values("date")
    dups = out["date"].duplicated(keep="last")
    if dups.any():
        logger.warning(
            "%s: dropping %d duplicate dates (keeping last)",
            ticker,
            int(dups.sum()),
        )
        out = out.loc[~dups]

    if out.empty:
        raise ValueError(f"{ticker}: no valid rows after cleaning")

    return out.set_index("date")


def load_fixture_prices(
    fixtures_dir: Path, tickers: list[str] | None = None
) -> dict[str, pd.DataFrame]:
    """Load cleaned daily prices for each ticker from fixture CSVs.

    Fixture files live at <fixtures_dir>/prices/<TICKER>.csv. If `tickers` is
    given, only those are loaded and every requested ticker must have a
    fixture file; if omitted, all available fixture files are loaded.
    Entirely offline by construction.
    """
    prices_dir = fixtures_dir / "prices"
    if not prices_dir.is_dir():
        raise FileNotFoundError(f"Fixture prices directory not found: {prices_dir}")

    available = {p.stem.upper(): p for p in sorted(prices_dir.glob("*.csv"))}
    if tickers is None:
        selected = available
    else:
        missing = [t for t in tickers if t not in available]
        if missing:
            raise FileNotFoundError(
                f"No fixture files for tickers: {missing} (in {prices_dir})"
            )
        selected = {t: available[t] for t in tickers}

    out: dict[str, pd.DataFrame] = {}
    for ticker, path in selected.items():
        raw = pd.read_csv(path)
        out[ticker] = clean_prices(raw, ticker)
        logger.info("%s: loaded %d fixture rows", ticker, len(out[ticker]))
    if not out:
        raise FileNotFoundError(f"No fixture CSVs found in {prices_dir}")
    return out
