"""Command-line entry points.

    etf-dislocations ingest --mode public [--tickers SPY LQD ...] [--price-source stooq|yahoo]
    etf-dislocations build-panel --mode fixture|public [--output PATH]
    etf-dislocations freeze --mode public --price-source yahoo [--name NAME] [--notes TEXT]

Fixture mode is fully offline. Public mode fetches prices and VIX from Stooq
by default (see docs/live_data_audit.md for its current anti-bot-challenge
status; --price-source yahoo is a documented fallback) and NAV from either a
manually downloaded file in data/raw/nav/ or, for SPDR-sponsored tickers, an
automated download (see docs/data_notes.md); `ingest` must be run before
`build-panel --mode public`.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from .analysis.event_study import run_event_study
from .analysis.mean_reversion import run_mean_reversion
from .analysis.panel_regression import load_regression_config, run_panel_regressions
from .analysis.robustness import placebo_event_study, regression_variants
from .config import Settings, load_data_sources, load_settings, repo_root
from .data.ingest_nav import ingest_nav, load_nav_dir
from .data.ingest_prices import ingest_prices, ingest_prices_yahoo
from .data.ingest_vix import ingest_vix, ingest_vix_yahoo, load_vix_csv
from .data.loaders import load_fixture_prices
from .freeze import build_provenance, freeze_panel
from .logging_utils import setup_logging
from .panel import build_panel
from .reporting.figures import plot_event_window
from .reporting.tables import (
    write_event_study_tables,
    write_mean_reversion_tables,
    write_regression_tables,
    write_robustness_tables,
)
from .stress.apply import add_stress_flags
from .stress.tier1_events import load_tier1_events
from .stress.tier2_rule import load_tier2_rules
from .universe import Universe, load_universe

logger = logging.getLogger(__name__)


def _ingest_command(
    mode: str, tickers: list[str] | None, price_source: str = "stooq"
) -> None:
    if mode != "public":
        raise SystemExit("ingest only applies to --mode public")
    settings = load_settings()
    universe = load_universe()
    sources = load_data_sources()

    selected = tickers if tickers else universe.tickers
    universe.subset(selected)  # validates tickers against the universe

    if price_source == "yahoo":
        logger.info("Using Yahoo Finance fallback price source (opt-in)")
        ingest_prices_yahoo(
            selected, sources.yahoo, settings.raw_dir, settings.processed_dir
        )
        ingest_vix_yahoo(sources.yahoo, settings.raw_dir, settings.processed_dir)
    else:
        ingest_prices(
            selected, sources.stooq, settings.raw_dir, settings.processed_dir
        )
        ingest_vix(sources.stooq, settings.raw_dir, settings.processed_dir)

    nav = ingest_nav(
        selected,
        settings.raw_dir / "nav",
        settings.processed_dir,
        sources.nav,
        spdr_cfg=sources.spdr_navhist,
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
    panel = add_stress_flags(panel, load_tier1_events(), load_tier2_rules())

    if output is None:
        output = settings.panel_dir / f"etf_day_panel_{mode}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(output, index=False)
    logger.info("Panel written to %s (%d rows)", output, len(panel))
    return output


def _event_study_command(
    mode: str, events_path: Path | None, output_dir: Path | None
) -> Path:
    settings = load_settings()
    panel = _load_built_panel(mode, settings)

    # Fixture mode defaults to the synthetic event window shipped with the
    # fixtures; public mode defaults to the pre-registered Tier-1 list.
    if events_path is None:
        events_path = _default_events_path(mode, settings)
    events = load_tier1_events(events_path)

    # Fixture outputs are quarantined from real results (SPEC.md 5.4).
    if output_dir is None:
        output_dir = _default_output_dir(mode)

    result = run_event_study(panel, events, settings.event_study)
    write_event_study_tables(result, output_dir)
    for event in result.bucket_means["event"].unique():
        plot_event_window(
            result.bucket_means, event, output_dir / f"event_{event}.png"
        )
    logger.info("Event-study outputs written to %s", output_dir)
    return output_dir


def _load_built_panel(mode: str, settings: Settings) -> pd.DataFrame:
    panel_path = settings.panel_dir / f"etf_day_panel_{mode}.csv"
    if not panel_path.is_file():
        raise SystemExit(
            f"No panel at {panel_path}; run "
            f"'etf-dislocations build-panel --mode {mode}' first"
        )
    return pd.read_csv(panel_path, parse_dates=["date"])


def _default_output_dir(mode: str) -> Path:
    reports = repo_root() / "reports"
    return reports / "fixture_run" if mode == "fixture" else reports


def _freeze_command(
    mode: str,
    price_source: str,
    name: str | None,
    notes: str | None,
    force: bool,
    output_dir: Path | None = None,
) -> Path:
    """Snapshot a built panel to data/frozen/ for reproducible paper writing.

    A live source changes day to day; this is the point at which the
    project stops depending on it for a given set of results.
    """
    settings = load_settings()
    panel = _load_built_panel(mode, settings)
    provenance = build_provenance(
        panel,
        mode=mode,
        price_source=price_source,
        retrieved=date.today().isoformat(),
        notes=notes,
    )
    parquet_path, provenance_path = freeze_panel(
        panel,
        output_dir if output_dir is not None else settings.frozen_dir,
        provenance,
        name=name,
        force=force,
    )
    logger.info(
        "Frozen snapshot: %s (provenance: %s)", parquet_path, provenance_path
    )
    return parquet_path


def _panel_regression_command(mode: str, output_dir: Path | None) -> Path:
    settings = load_settings()
    panel = _load_built_panel(mode, settings)
    cfg = load_regression_config()

    coefficients, stats = run_panel_regressions(panel, cfg)
    if output_dir is None:
        output_dir = _default_output_dir(mode)
    write_regression_tables(coefficients, stats, output_dir)
    logger.info("Regression outputs written to %s", output_dir)
    return output_dir


def _mean_reversion_command(mode: str, output_dir: Path | None) -> Path:
    settings = load_settings()
    panel = _load_built_panel(mode, settings)

    half_lives, regime_tests = run_mean_reversion(
        panel, settings.mean_reversion.min_obs
    )
    if output_dir is None:
        output_dir = _default_output_dir(mode)
    write_mean_reversion_tables(half_lives, regime_tests, output_dir)
    logger.info("Mean-reversion outputs written to %s", output_dir)
    return output_dir


def _default_events_path(mode: str, settings: Settings) -> Path:
    return (
        settings.fixtures_dir / "stress_windows.yaml"
        if mode == "fixture"
        else repo_root() / "config" / "stress_windows.yaml"
    )


def _robustness_command(
    mode: str, output_dir: Path | None, exclude_event: str | None
) -> Path:
    settings = load_settings()
    panel = _load_built_panel(mode, settings)
    events = load_tier1_events(_default_events_path(mode, settings))
    reg_cfg = load_regression_config()
    rules = load_tier2_rules()

    rob = settings.robustness
    if exclude_event is not None:
        rob = dataclasses.replace(rob, exclude_event=exclude_event)
    elif mode == "fixture" and rob.exclude_event not in {e.name for e in events}:
        # The settings default names a real Tier-1 event; in fixture mode
        # fall back to the synthetic event so the exclusion check still runs.
        rob = dataclasses.replace(rob, exclude_event=events[0].name)
        logger.info(
            "Fixture mode: exclusion check uses %r", rob.exclude_event
        )

    regressions = regression_variants(panel, reg_cfg, rules, events, rob)
    placebo = placebo_event_study(panel, events, settings.event_study, rob)

    if output_dir is None:
        output_dir = _default_output_dir(mode)
    write_robustness_tables(regressions, placebo, output_dir)
    logger.info("Robustness outputs written to %s", output_dir)
    return output_dir


def _write_manifest(output_dir: Path, mode: str) -> Path:
    """Write a deterministic manifest of every output file: name, sha256,
    and row count for CSVs. No timestamps, so identical runs produce
    identical manifests - the manifest itself is the reproducibility check.
    """
    from . import __version__

    entries = []
    for path in sorted(output_dir.glob("*")):
        if path.name == "run_manifest.json" or not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entry = {"file": path.name, "sha256": digest}
        if path.suffix == ".csv":
            with open(path, encoding="utf-8") as f:
                entry["rows"] = sum(1 for _ in f) - 1
        entries.append(entry)

    manifest = {"mode": mode, "package_version": __version__, "outputs": entries}
    path = output_dir / "run_manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote %s (%d outputs)", path, len(entries))
    return path


def _run_all_command(
    mode: str, output_dir: Path | None, exclude_event: str | None
) -> Path:
    """Full pipeline: panel -> event study -> regression -> mean reversion
    -> robustness -> manifest, in one command."""
    if output_dir is None:
        output_dir = _default_output_dir(mode)

    _build_panel_command(mode, None)
    _event_study_command(mode, None, output_dir)
    _panel_regression_command(mode, output_dir)
    _mean_reversion_command(mode, output_dir)
    _robustness_command(mode, output_dir, exclude_event)
    _write_manifest(output_dir, mode)
    logger.info("Full pipeline complete; outputs in %s", output_dir)
    return output_dir


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
    p_ingest.add_argument(
        "--price-source",
        choices=["stooq", "yahoo"],
        default="stooq",
        help="Price/VIX source; stooq is the documented default (currently "
        "blocked by an anti-bot challenge - see docs/live_data_audit.md), "
        "yahoo is an opt-in fallback",
    )

    p_panel = sub.add_parser(
        "build-panel", help="Build the ETF-day panel with dislocation measures"
    )
    p_panel.add_argument("--mode", choices=["fixture", "public"], default="fixture")
    p_panel.add_argument("--output", type=Path, default=None, help="Output CSV path")

    p_es = sub.add_parser(
        "event-study", help="Run the dislocation event study on a built panel"
    )
    p_es.add_argument("--mode", choices=["fixture", "public"], default="fixture")
    p_es.add_argument(
        "--events",
        type=Path,
        default=None,
        help="Event-window YAML (default: fixture events or Tier-1 config)",
    )
    p_es.add_argument(
        "--output-dir", type=Path, default=None, help="Directory for outputs"
    )

    p_reg = sub.add_parser(
        "panel-regression",
        help="Run the fixed panel regression specifications on a built panel",
    )
    p_reg.add_argument("--mode", choices=["fixture", "public"], default="fixture")
    p_reg.add_argument(
        "--output-dir", type=Path, default=None, help="Directory for outputs"
    )

    p_mr = sub.add_parser(
        "mean-reversion",
        help="Estimate AR(1) half-lives of the premium/discount by regime",
    )
    p_mr.add_argument("--mode", choices=["fixture", "public"], default="fixture")
    p_mr.add_argument(
        "--output-dir", type=Path, default=None, help="Directory for outputs"
    )

    p_rob = sub.add_parser(
        "robustness", help="Run the robustness suite on a built panel"
    )
    p_rob.add_argument("--mode", choices=["fixture", "public"], default="fixture")
    p_rob.add_argument(
        "--output-dir", type=Path, default=None, help="Directory for outputs"
    )
    p_rob.add_argument(
        "--exclude-event",
        default=None,
        help="Tier-1 event dropped in the exclusion check (default from settings)",
    )

    p_all = sub.add_parser(
        "run-all",
        help="Run the full pipeline: panel, event study, regression, "
        "mean reversion, robustness",
    )
    p_all.add_argument("--mode", choices=["fixture", "public"], default="fixture")
    p_all.add_argument(
        "--output-dir", type=Path, default=None, help="Directory for outputs"
    )
    p_all.add_argument(
        "--exclude-event",
        default=None,
        help="Tier-1 event dropped in the robustness exclusion check",
    )

    p_freeze = sub.add_parser(
        "freeze",
        help="Snapshot a built panel to data/frozen/ for reproducible paper writing",
    )
    p_freeze.add_argument("--mode", choices=["fixture", "public"], default="public")
    p_freeze.add_argument(
        "--price-source",
        choices=["stooq", "yahoo", "fixture"],
        default="stooq",
        help="Price source used to build the panel being frozen, recorded "
        "in the provenance record (not re-fetched)",
    )
    p_freeze.add_argument(
        "--name",
        default=None,
        help="Snapshot base name (default: etf_panel_<today's date>)",
    )
    p_freeze.add_argument(
        "--notes", default=None, help="Free-text note stored in the provenance record"
    )
    p_freeze.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing snapshot of the same name (snapshots "
        "are meant to be permanent; use only to intentionally replace one)",
    )
    p_freeze.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for the snapshot (default: data/frozen/)",
    )

    args = parser.parse_args(argv)
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    if args.command == "ingest":
        _ingest_command(args.mode, args.tickers, args.price_source)
    elif args.command == "build-panel":
        _build_panel_command(args.mode, args.output)
    elif args.command == "event-study":
        _event_study_command(args.mode, args.events, args.output_dir)
    elif args.command == "panel-regression":
        _panel_regression_command(args.mode, args.output_dir)
    elif args.command == "mean-reversion":
        _mean_reversion_command(args.mode, args.output_dir)
    elif args.command == "robustness":
        _robustness_command(args.mode, args.output_dir, args.exclude_event)
    elif args.command == "run-all":
        _run_all_command(args.mode, args.output_dir, args.exclude_event)
    elif args.command == "freeze":
        _freeze_command(
            args.mode, args.price_source, args.name, args.notes, args.force,
            args.output_dir,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
