"""Command-line entry point.

Milestone 1 exposes one command:

    etf-dislocations build-panel --mode fixture [--output PATH]

Fixture mode is fully offline. Public mode is reserved for the Milestone 2+
ingestion work and is rejected explicitly rather than stubbed.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_settings
from .data.loaders import load_fixture_prices
from .logging_utils import setup_logging
from .panel import build_panel
from .universe import load_universe

logger = logging.getLogger(__name__)


def _build_panel_command(mode: str, output: Path | None) -> Path:
    settings = load_settings()
    universe = load_universe()

    if mode != "fixture":
        raise SystemExit(
            f"Mode {mode!r} is not implemented yet; only 'fixture' is "
            "available in Milestone 1."
        )

    # Fixtures deliberately cover a subset of the universe; load what exists
    # and log the coverage so a partial sample is never silent.
    prices = load_fixture_prices(settings.fixtures_dir)
    unknown = sorted(set(prices) - set(universe.tickers))
    if unknown:
        raise SystemExit(f"Fixture tickers not in universe: {unknown}")
    covered = sorted(prices)
    logger.info(
        "Fixture coverage: %d/%d universe tickers (%s)",
        len(covered),
        len(universe.tickers),
        ", ".join(covered),
    )

    panel = build_panel(prices, universe, settings.liquidity)

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

    p_panel = sub.add_parser(
        "build-panel", help="Build the ETF-day panel with liquidity metrics"
    )
    p_panel.add_argument(
        "--mode",
        choices=["fixture", "public"],
        default="fixture",
        help="Data source mode (only 'fixture' is implemented in Milestone 1)",
    )
    p_panel.add_argument(
        "--output", type=Path, default=None, help="Output CSV path"
    )

    args = parser.parse_args(argv)
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    if args.command == "build-panel":
        _build_panel_command(args.mode, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
