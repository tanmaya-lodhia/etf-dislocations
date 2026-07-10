"""Public-mode daily price ingestion via Stooq's CSV download endpoint.

One GET per ticker per run against a documented download URL (no scraping).
The network fetch is injectable so tests exercise parsing and caching fully
offline. Raw responses are cached under data/raw/prices/ before parsing;
cleaned frames are written to data/processed/prices/.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd

from ..config import StooqConfig
from .loaders import clean_prices

logger = logging.getLogger(__name__)

STOOQ_COLUMNS = {
    "Date": "date",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
}

Fetcher = Callable[[str], str]


def fetch_stooq_csv(url: str) -> str:
    """Download one CSV from Stooq. Only called in public mode."""
    import requests

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_stooq_csv(text: str, ticker: str) -> pd.DataFrame:
    """Parse a Stooq daily CSV response into a cleaned OHLCV frame.

    Stooq answers unknown symbols with a short plain-text message rather than
    an HTTP error, so that case is detected here.
    """
    if "Date" not in text.splitlines()[0]:
        raise ValueError(
            f"{ticker}: response is not a Stooq CSV "
            f"(starts with {text[:40]!r}); check the symbol mapping"
        )
    raw = pd.read_csv(io.StringIO(text))
    missing = [c for c in STOOQ_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"{ticker}: Stooq CSV missing columns {missing}")
    raw = raw.rename(columns=STOOQ_COLUMNS)
    return clean_prices(raw, ticker)


def ingest_prices(
    tickers: list[str],
    stooq: StooqConfig,
    raw_dir: Path,
    processed_dir: Path,
    fetch: Fetcher = fetch_stooq_csv,
) -> dict[str, pd.DataFrame]:
    """Fetch, cache, clean, and persist daily prices for the given tickers.

    Returns the cleaned frames keyed by ticker. Raw responses are stamped
    with the download date; processed CSVs are overwritten in place.
    """
    unmapped = [t for t in tickers if t not in stooq.price_symbols]
    if unmapped:
        raise KeyError(f"No Stooq symbol configured for: {unmapped}")

    raw_prices = raw_dir / "prices"
    out_dir = processed_dir / "prices"
    raw_prices.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = date.today().isoformat()
    out: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        url = stooq.url_template.format(symbol=stooq.price_symbols[ticker])
        text = fetch(url)
        (raw_prices / f"{ticker}_{stamp}.csv").write_text(text, encoding="utf-8")
        df = parse_stooq_csv(text, ticker)
        df.reset_index().to_csv(out_dir / f"{ticker}.csv", index=False)
        out[ticker] = df
        logger.info("%s: ingested %d rows from Stooq", ticker, len(df))
    return out
