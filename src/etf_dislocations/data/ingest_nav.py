"""Daily NAV ingestion, primarily from manually downloaded sponsor files,
with an automated fallback for State Street/SPDR-sponsored tickers.

For most sponsors there is no reliable free API for historical ETF NAV, so
public mode expects one CSV per ticker at data/raw/nav/<TICKER>.csv,
downloaded by hand from the sponsor's fund page (instructions in
docs/data_notes.md). Header spellings vary by sponsor; accepted variants are
configured in data_sources.yaml. Cleaned series are persisted to
data/processed/nav/ in a canonical date,nav format, which is also the
fixture format.

State Street/SPDR is the one sponsor found to publish a documented, keyless
daily NAV history export per fund (see docs/live_data_audit.md); for the
tickers listed under spdr_navhist in data_sources.yaml, ingest_nav()
downloads this automatically when no manual CSV is present. A manually
placed CSV always takes priority, so this never silently overrides a
user-supplied file.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd

from ..config import NavConfig, SpdrNavConfig

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


def fetch_spdr_navhist_xlsx(url: str) -> bytes:
    """Download one NAV-history workbook from State Street's fund-data
    export. A single documented, keyless GET per fund; only called in
    public mode as an automated NAV fallback."""
    import requests

    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.content


def parse_spdr_navhist_xlsx(content: bytes, ticker: str) -> pd.Series:
    """Parse a State Street "navhist" workbook into a date-indexed NAV
    series.

    The sheet has a 3-row header block (fund name, ticker, blank) before the
    real Date/NAV/Shares Outstanding/Total Net Assets header, and a trailing
    disclaimer footer with blank or text-only rows; both are dropped by
    requiring a parseable positive NAV.
    """
    try:
        raw = pd.read_excel(
            io.BytesIO(content), sheet_name="navhist", skiprows=3
        )
    except (ValueError, KeyError) as exc:
        raise ValueError(
            f"{ticker}: SPDR navhist workbook missing expected 'navhist' "
            f"sheet"
        ) from exc

    if not {"Date", "NAV"}.issubset(raw.columns):
        raise ValueError(
            f"{ticker}: SPDR navhist sheet missing Date/NAV columns "
            f"(found {list(raw.columns)})"
        )

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["Date"], format="%d-%b-%Y", errors="coerce"),
            "nav": pd.to_numeric(raw["NAV"], errors="coerce"),
        }
    )
    out = out.dropna(subset=["date"])
    n_before = len(out)
    out = out.loc[out["nav"].gt(0)]
    dropped = n_before - len(out)
    if dropped:
        logger.warning(
            "%s: dropped %d SPDR navhist rows (missing or <= 0 NAV)",
            ticker, dropped,
        )
    out = out.sort_values("date")
    out = out.loc[~out["date"].duplicated(keep="last")]
    if out.empty:
        raise ValueError(f"{ticker}: no valid NAV rows in SPDR navhist workbook")
    return out.set_index("date")["nav"]


def ingest_nav(
    tickers: list[str],
    raw_nav_dir: Path,
    processed_dir: Path,
    nav_cfg: NavConfig,
    require_all: bool = False,
    spdr_cfg: SpdrNavConfig | None = None,
    spdr_fetch=fetch_spdr_navhist_xlsx,
) -> dict[str, pd.Series]:
    """Parse NAV data and persist canonical date,nav CSVs.

    For each ticker: a manually placed data/raw/nav/<TICKER>.csv is used if
    present; otherwise, if spdr_cfg is given and the ticker is listed there,
    NAV is downloaded automatically from State Street's navhist export.
    Tickers satisfied by neither path are skipped with a warning (or an
    error when require_all is set), so a partial NAV sample is always
    visible in logs.
    """
    out_dir = processed_dir / "nav"
    out_dir.mkdir(parents=True, exist_ok=True)

    out: dict[str, pd.Series] = {}
    missing: list[str] = []
    for ticker in tickers:
        path = raw_nav_dir / f"{ticker}.csv"
        if path.is_file():
            nav = parse_nav_csv(pd.read_csv(path), ticker, nav_cfg)
            logger.info("%s: ingested %d NAV rows (manual CSV)", ticker, len(nav))
        elif spdr_cfg is not None and ticker in spdr_cfg.tickers:
            url = spdr_cfg.url_template.format(symbol=ticker.lower())
            content = spdr_fetch(url)
            nav = parse_spdr_navhist_xlsx(content, ticker)
            logger.info(
                "%s: ingested %d NAV rows (automated SPDR navhist)",
                ticker, len(nav),
            )
        else:
            missing.append(ticker)
            continue
        nav.reset_index().to_csv(out_dir / f"{ticker}.csv", index=False)
        out[ticker] = nav

    if missing:
        msg = (
            f"No NAV source for {len(missing)} tickers: {missing} "
            f"(expected <TICKER>.csv in {raw_nav_dir}, or a spdr_navhist "
            f"config entry)"
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
