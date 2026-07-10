"""VIX daily level ingestion (Stooq) and loading.

The VIX close is used by the Tier-2 stress-day rule in later milestones and
joined onto the panel now so the panel schema is stable. Same offline-testable
structure as price ingestion: fetch is injectable, parsing is pure.
"""

from __future__ import annotations

import io
import logging
from datetime import date
from pathlib import Path

import pandas as pd

from ..config import StooqConfig
from .ingest_prices import Fetcher, fetch_stooq_csv

logger = logging.getLogger(__name__)


def parse_vix_csv(text: str) -> pd.Series:
    """Parse a Stooq daily CSV into a date-indexed VIX close series."""
    if "Date" not in text.splitlines()[0]:
        raise ValueError(
            f"VIX response is not a Stooq CSV (starts with {text[:40]!r})"
        )
    raw = pd.read_csv(io.StringIO(text))
    if "Close" not in raw.columns or "Date" not in raw.columns:
        raise ValueError("VIX CSV missing Date/Close columns")
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["Date"]).dt.normalize(),
            "vix": pd.to_numeric(raw["Close"], errors="coerce"),
        }
    )
    out = out.dropna().sort_values("date")
    out = out.loc[~out["date"].duplicated(keep="last")]
    if out.empty:
        raise ValueError("VIX CSV contained no valid rows")
    return out.set_index("date")["vix"]


def ingest_vix(
    stooq: StooqConfig,
    raw_dir: Path,
    processed_dir: Path,
    fetch: Fetcher = fetch_stooq_csv,
) -> pd.Series:
    """Fetch, cache, and persist the VIX daily close series."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    url = stooq.url_template.format(symbol=stooq.vix_symbol)
    text = fetch(url)
    stamp = date.today().isoformat()
    (raw_dir / f"vix_{stamp}.csv").write_text(text, encoding="utf-8")

    vix = parse_vix_csv(text)
    vix.reset_index().to_csv(processed_dir / "vix.csv", index=False)
    logger.info("VIX: ingested %d rows from Stooq", len(vix))
    return vix


def load_vix_csv(path: Path) -> pd.Series:
    """Load a persisted (or fixture) VIX series from date,vix CSV."""
    raw = pd.read_csv(path)
    if not {"date", "vix"}.issubset(raw.columns):
        raise ValueError(f"{path}: expected columns date,vix")
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["date"]).dt.normalize(),
            "vix": pd.to_numeric(raw["vix"], errors="coerce"),
        }
    ).dropna()
    out = out.sort_values("date")
    out = out.loc[~out["date"].duplicated(keep="last")]
    return out.set_index("date")["vix"]
