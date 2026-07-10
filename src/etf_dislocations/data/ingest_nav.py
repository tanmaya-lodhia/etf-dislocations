"""Daily NAV ingestion from manually downloaded sponsor files.

There is no reliable free API for historical ETF NAV, so public mode expects
one CSV per ticker at data/raw/nav/<TICKER>.csv, downloaded by hand from the
sponsor's fund page (instructions in docs/data_notes.md). Header spellings
vary by sponsor; accepted variants are configured in data_sources.yaml.
Cleaned series are persisted to data/processed/nav/ in a canonical date,nav
format, which is also the fixture format.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..config import NavConfig

logger = logging.getLogger(__name__)


def parse_nav_csv(raw: pd.DataFrame, ticker: str, nav_cfg: NavConfig) -> pd.Series:
    """Normalise a sponsor NAV download into a date-indexed NAV series.

    Picks the first configured header spelling present for each of date and
    NAV, drops non-positive or missing NAVs, sorts, and dedupes (keeping the
    last observation per date).
    """
    date_col = next((c for c in nav_cfg.date_columns if c in raw.columns), None)
    nav_col = next((c for c in nav_cfg.nav_columns if c in raw.columns), None)
    if date_col is None or nav_col is None:
        raise ValueError(
            f"{ticker}: could not find date/NAV columns in {list(raw.columns)}; "
            f"accepted spellings are configured in data_sources.yaml"
        )

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[date_col], errors="raise").dt.normalize(),
            "nav": pd.to_numeric(raw[nav_col], errors="coerce"),
        }
    )
    n_before = len(out)
    out = out.loc[out["nav"].gt(0)]
    dropped = n_before - len(out)
    if dropped:
        logger.warning("%s: dropped %d NAV rows (missing or <= 0)", ticker, dropped)
    out = out.sort_values("date")
    out = out.loc[~out["date"].duplicated(keep="last")]
    if out.empty:
        raise ValueError(f"{ticker}: no valid NAV rows after cleaning")
    return out.set_index("date")["nav"]


def ingest_nav(
    tickers: list[str],
    raw_nav_dir: Path,
    processed_dir: Path,
    nav_cfg: NavConfig,
    require_all: bool = False,
) -> dict[str, pd.Series]:
    """Parse manual NAV downloads and persist canonical date,nav CSVs.

    Tickers without a raw file are skipped with a warning (or an error when
    require_all is set), so a partial NAV sample is always visible in logs.
    """
    out_dir = processed_dir / "nav"
    out_dir.mkdir(parents=True, exist_ok=True)

    out: dict[str, pd.Series] = {}
    missing: list[str] = []
    for ticker in tickers:
        path = raw_nav_dir / f"{ticker}.csv"
        if not path.is_file():
            missing.append(ticker)
            continue
        nav = parse_nav_csv(pd.read_csv(path), ticker, nav_cfg)
        nav.reset_index().to_csv(out_dir / f"{ticker}.csv", index=False)
        out[ticker] = nav
        logger.info("%s: ingested %d NAV rows", ticker, len(nav))

    if missing:
        msg = (
            f"No NAV file for {len(missing)} tickers: {missing} "
            f"(expected <TICKER>.csv in {raw_nav_dir})"
        )
        if require_all:
            raise FileNotFoundError(msg)
        logger.warning(msg)
    return out


def load_nav_dir(nav_dir: Path, tickers: list[str] | None = None) -> dict[str, pd.Series]:
    """Load canonical date,nav CSVs (fixtures or processed output).

    If `tickers` is given, every requested ticker must be present; otherwise
    all available files are loaded.
    """
    if not nav_dir.is_dir():
        raise FileNotFoundError(f"NAV directory not found: {nav_dir}")
    available = {p.stem.upper(): p for p in sorted(nav_dir.glob("*.csv"))}
    if tickers is None:
        selected = available
    else:
        missing = [t for t in tickers if t not in available]
        if missing:
            raise FileNotFoundError(f"No NAV files for: {missing} (in {nav_dir})")
        selected = {t: available[t] for t in tickers}

    out: dict[str, pd.Series] = {}
    for ticker, path in selected.items():
        raw = pd.read_csv(path)
        if not {"date", "nav"}.issubset(raw.columns):
            raise ValueError(f"{path}: expected canonical columns date,nav")
        s = pd.Series(
            pd.to_numeric(raw["nav"], errors="coerce").values,
            index=pd.to_datetime(raw["date"]).dt.normalize(),
            name="nav",
        ).dropna()
        s = s[~s.index.duplicated(keep="last")].sort_index()
        if s.empty:
            raise ValueError(f"{path}: no valid NAV rows")
        out[ticker] = s
    return out
