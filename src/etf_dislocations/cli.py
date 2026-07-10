"""Command-line entry points.

    etf-dislocations ingest --mode public [--tickers SPY LQD ...]
    etf-dislocations build-panel --mode fixture|public [--output PATH]

Fixture mode is fully offline. Public mode fetches prices and VIX from Stooq
and parses manually downloaded NAV files from data/raw/nav/ (see
docs/data_notes.md); `ingest` must be run before `build-panel --mode public`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import Settings, load_data_sources, load_settings
from .data.ingest_nav import ingest_nav, load_nav_dir
from .data.ingest_prices import ingest_prices
from .data.ingest_vix import ingest_vix, load_vix_csv
from .data.loaders import load_fixture_prices
from .logging_utils import setup_logging
from .panel import build_panel
from .universe import Universe, load_universe

logger = logging.getLogger(__name__)


def _ingest_command(mode: str, tickers: list[str] | None) -> None:
    if mode != "public":
        raise SystemExit("ingest only applies to --mode public")
    settings = load_settings()
    universe = load_universe()
    sources = load_data_sources()

    selected = tickers if tickers else universe.tickers
    universe.subset(selected)  # validates tickers against the universe

    ingest_prices(
        selected, sources.stooq, settings.raw_dir, settings.processed_dir
    )
    ingest_vix(sources.stooq, settings.raw_dir, settings.processed_dir)
    nav = ingest_nav(
        selected, settings.raw_dir / "nav", settings.processed_dir, sources.nav
    )
    logger.info(
        "Ingestion complete: %d tickers, NAV available for %d",
        len(selected),
        len(nav),
    )


def _load_inputs(mode: str, settings: Settings, universe: Universe):
    """Load prices, NAV, and VIX for the requested mode."""
    if mode == "fixture":
        base = settings.fixtures_dir
        prices = load_fixture_prices(base)
        nav = load_nav_dir(base / "nav")
        vix = load_vix_csv(base / "vix.csv")
    else:
        prices_dir = settings.processed_dir / "prices"
        if not prices_dir.is_dir():
            raise SystemExit(
                "No processed prices found; run "
                "'etf-dislocations ingest --mode public' first"
            )
        prices = load_fixture_prices(settings.processed_dir)
        nav_dir = settings.processed_dir / "nav"
        nav = load_nav_dir(nav_dir) if nav_dir.is_dir() else {}
        vix_path = settings.processed_dir / "vix.csv"
        vix = load_vix_csv(vix_path) if vix_path.is_file() else None

    unknown = sorted(set(prices) - set(universe.tickers))
    if unknown:
        raise SystemExit(f"Price tickers not in universe: {unknown}")
    no_nav = sorted(set(prices) - set(nav))
    if no_nav:
        logger.warning(
            "No NAV for %d tickers (%s): premium/discount will be NaN",
            len(no_nav),
            ", ".join(no_nav),
        )
    return prices, nav, vix


def _build_panel_command(mode: str, output: Path | None) -> Path:
    settings = load_settings()
    universe = load_universe()
    sources = load_data_sources()

    prices, nav, vix = _load_inputs(mode, settings, universe)
    logger.info(
        "Coverage: %d/%d universe tickers (%s)",
        len(prices),
        len(universe.tickers),
        ", ".join(sorted(prices)),
    )

    panel = build_panel(
        prices,
        universe,
        settings.liquidity,
        nav=nav,
        vix=vix,
        foreign_calendars=sources.foreign_calendars,
    )

    if output is None:
        output = settings.panel_dir / f"etf_day_panel_{mode}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(output, index=False)
    logger.info("Panel written to %s (%d rows)", output, len(panel))
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etf-dislocations")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser(
        "ingest", help="Fetch public price/VIX data and parse NAV downloads"
    )
    p_ingest.add_argument("--mode", choices=["public"], default="public")
    p_ingest.add_argument(
        "--tickers",
        nargs="+",
        metavar="TICKER",
        help="Subset of the universe to ingest (default: all)",
    )

    p_panel = sub.add_parser(
        "build-panel", help="Build the ETF-day panel with dislocation measures"
    )
    p_panel.add_argument("--mode", choices=["fixture", "public"], default="fixture")
    p_panel.add_argument("--output", type=Path, default=None, help="Output CSV path")

    args = parser.parse_args(argv)
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    if args.command == "ingest":
        _ingest_command(args.mode, args.tickers)
    elif args.command == "build-panel":
        _build_panel_command(args.mode, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
