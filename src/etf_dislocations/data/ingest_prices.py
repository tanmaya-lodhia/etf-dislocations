"""Public-mode daily price ingestion via Stooq's CSV download endpoint, with
a documented Yahoo Finance fallback.

One GET per ticker per run against a documented download URL (no scraping).
The network fetch is injectable so tests exercise parsing and caching fully
offline. Raw responses are cached under data/raw/prices/ before parsing;
cleaned frames are written to data/processed/prices/.

As of 2026-07-10, Stooq's download endpoint serves a client-side JS
proof-of-work anti-bot challenge to every request rather than CSV data (see
docs/live_data_audit.md). It is kept as the configured default; `ingest
--price-source yahoo` opts into the Yahoo chart-JSON fallback below instead.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd

from ..config import StooqConfig, YahooConfig
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

# Substring unique to the anti-bot challenge page observed on Stooq's
# endpoint since 2026-07; used only to give a diagnosable error, not to
# defeat the challenge.
STOOQ_BOT_CHALLENGE_MARKER = "requires JavaScript to verify your browser"

Fetcher = Callable[[str], str]


def fetch_stooq_csv(url: str) -> str:
    """Download one CSV from Stooq. Only called in public mode."""
    import requests

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_stooq_csv(text: str, ticker: str) -> pd.DataFrame:
    """Parse a Stooq daily CSV response into a cleaned OHLCV frame.

    Stooq answers unknown symbols, and its anti-bot challenge page, with a
    200 OK containing HTML rather than CSV; both are detected here so the
    failure is diagnosable instead of a downstream parse error.
    """
    first_line = text.splitlines()[0] if text else ""
    if STOOQ_BOT_CHALLENGE_MARKER in text:
        raise ValueError(
            f"{ticker}: Stooq returned its anti-bot JS challenge page instead "
            f"of CSV data. This is a known site-wide issue as of 2026-07-10 "
            f"(see docs/live_data_audit.md) - not a symbol-mapping problem. "
            f"Use 'ingest --price-source yahoo' as a documented fallback."
        )
    if "Date" not in first_line:
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


def fetch_yahoo_chart_json(url: str) -> str:
    """Download one chart response from Yahoo's public chart JSON endpoint.

    This is the same endpoint the `yfinance` library wraps (named as an
    acceptable source in SPEC.md section 2.2): a single GET returning JSON,
    no key, no scraping. Only called in public mode with --price-source
    yahoo.
    """
    import requests

    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.text


def parse_yahoo_chart_json(text: str, ticker: str) -> pd.DataFrame:
    """Parse a Yahoo chart JSON response into a cleaned OHLCV frame.

    Yahoo's `close` field is unadjusted for dividends/splits (a separate
    `adjclose` field carries the dividend-adjusted series, which this project
    does not use - see docs/data_notes.md on the same convention for Stooq).
    Timestamps are UTC seconds at the exchange's local session time; since
    every sample ticker's session falls in the local morning, converting via
    UTC date never rolls over to the wrong calendar day, but this is
    documented rather than assumed for tickers added later.
    """
    import json

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{ticker}: Yahoo response is not valid JSON (starts with "
            f"{text[:60]!r})"
        ) from exc

    error = payload.get("chart", {}).get("error")
    if error:
        raise ValueError(f"{ticker}: Yahoo chart API error: {error}")
    results = payload.get("chart", {}).get("result")
    if not results:
        raise ValueError(f"{ticker}: Yahoo chart API returned no result")

    result = results[0]
    timestamps = result.get("timestamp")
    quote = result.get("indicators", {}).get("quote", [{}])[0]
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in quote]
    if not timestamps or missing:
        raise ValueError(
            f"{ticker}: Yahoo chart API response missing timestamps or "
            f"{missing}"
        )

    raw = pd.DataFrame(
        {
            "date": pd.to_datetime(timestamps, unit="s", utc=True).tz_localize(
                None
            ),
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "close": quote["close"],
            "volume": quote["volume"],
        }
    )
    return clean_prices(raw, ticker)


def ingest_prices_yahoo(
    tickers: list[str],
    yahoo: YahooConfig,
    raw_dir: Path,
    processed_dir: Path,
    fetch: Fetcher = fetch_yahoo_chart_json,
) -> dict[str, pd.DataFrame]:
    """Fetch, cache, clean, and persist daily prices from Yahoo.

    Mirrors ingest_prices() but writes raw responses with a `_yahoo_` stamp
    so cached files from the two sources are never confused, and processed
    output for the same ticker from either source lands at the same path
    (whichever ran most recently wins - both produce the same cleaned
    schema).
    """
    unmapped = [t for t in tickers if t not in yahoo.price_symbols]
    if unmapped:
        raise KeyError(f"No Yahoo symbol configured for: {unmapped}")

    raw_prices = raw_dir / "prices"
    out_dir = processed_dir / "prices"
    raw_prices.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = date.today().isoformat()
    out: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        url = yahoo.url_template.format(symbol=yahoo.price_symbols[ticker])
        text = fetch(url)
        (raw_prices / f"{ticker}_yahoo_{stamp}.csv").write_text(
            text, encoding="utf-8"
        )
        df = parse_yahoo_chart_json(text, ticker)
        df.reset_index().to_csv(out_dir / f"{ticker}.csv", index=False)
        out[ticker] = df
        logger.info("%s: ingested %d rows from Yahoo", ticker, len(df))
    return out
