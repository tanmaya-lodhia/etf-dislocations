"""ETF universe: the pre-registered ticker list and asset-class buckets.

The universe is fixed in config/universe.yaml (SPEC.md section 2.1) and must
not be modified after estimation begins. This module only parses and exposes
it; it never edits it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import repo_root

VALID_BUCKETS = frozenset(
    {
        "domestic_equity",
        "sector_equity",
        "international_equity",
        "ig_credit",
        "hy_credit",
        "rates",
    }
)


@dataclass(frozen=True)
class EtfEntry:
    ticker: str
    bucket: str


@dataclass(frozen=True)
class Universe:
    entries: tuple[EtfEntry, ...]

    @property
    def tickers(self) -> list[str]:
        return [e.ticker for e in self.entries]

    def bucket_of(self, ticker: str) -> str:
        for e in self.entries:
            if e.ticker == ticker:
                return e.bucket
        raise KeyError(f"Ticker {ticker!r} is not in the universe")

    def subset(self, tickers: list[str]) -> "Universe":
        """Restrict to the given tickers, preserving universe order.

        Raises if any requested ticker is not in the universe, so a typo
        cannot silently shrink the sample.
        """
        known = set(self.tickers)
        missing = [t for t in tickers if t not in known]
        if missing:
            raise KeyError(f"Tickers not in universe: {missing}")
        keep = set(tickers)
        return Universe(tuple(e for e in self.entries if e.ticker in keep))


def load_universe(path: Path | None = None) -> Universe:
    """Load and validate the universe from config/universe.yaml."""
    if path is None:
        path = repo_root() / "config" / "universe.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    entries = []
    seen: set[str] = set()
    for item in cfg["etfs"]:
        ticker = str(item["ticker"]).upper()
        bucket = str(item["bucket"])
        if bucket not in VALID_BUCKETS:
            raise ValueError(
                f"Unknown bucket {bucket!r} for {ticker}; "
                f"valid buckets: {sorted(VALID_BUCKETS)}"
            )
        if ticker in seen:
            raise ValueError(f"Duplicate ticker in universe: {ticker}")
        seen.add(ticker)
        entries.append(EtfEntry(ticker=ticker, bucket=bucket))

    if not entries:
        raise ValueError("Universe is empty")
    return Universe(tuple(entries))
