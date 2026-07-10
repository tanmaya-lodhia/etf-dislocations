"""End-to-end fixture-mode pipeline test. Runs completely offline:
fixtures -> load -> clean -> panel -> dislocation + liquidity -> output CSV.
"""

import pandas as pd

from etf_dislocations.cli import main
from etf_dislocations.config import load_data_sources, load_settings
from etf_dislocations.data.ingest_nav import load_nav_dir
from etf_dislocations.data.ingest_vix import load_vix_csv
from etf_dislocations.data.loaders import load_fixture_prices
from etf_dislocations.panel import PANEL_COLUMNS, build_panel
from etf_dislocations.stress.apply import STRESS_COLUMNS, add_stress_flags
from etf_dislocations.stress.tier1_events import load_tier1_events
from etf_dislocations.stress.tier2_rule import load_tier2_rules
from etf_dislocations.universe import load_universe

FIXTURE_TICKERS = {"SPY", "EFA", "LQD", "HYG", "TLT"}


def test_full_pipeline_from_fixtures(tmp_path):
    settings = load_settings()
    universe = load_universe()
    sources = load_data_sources()

    prices = load_fixture_prices(settings.fixtures_dir)
    nav = load_nav_dir(settings.fixtures_dir / "nav")
    vix = load_vix_csv(settings.fixtures_dir / "vix.csv")
    panel = build_panel(
        prices,
        universe,
        settings.liquidity,
        nav=nav,
        vix=vix,
        foreign_calendars=sources.foreign_calendars,
    )

    # Shape: 5 tickers x 130 fixture days, one row per ETF-day.
    assert set(panel["ticker"]) == FIXTURE_TICKERS
    assert len(panel) == 5 * 130
    assert list(panel.columns) == PANEL_COLUMNS
    assert not panel.duplicated(subset=["ticker", "date"]).any()

    # Core measures populated once rolling windows fill.
    w = settings.liquidity.rolling_window
    vw = settings.liquidity.volume_window
    for _, grp in panel.groupby("ticker"):
        assert grp["dollar_volume"].notna().all()
        assert grp["nav"].notna().all()
        assert grp["premium_discount"].notna().all()
        assert grp["ret"].iloc[1:].notna().all()
        assert grp["realized_vol"].iloc[w:].notna().all()
        assert grp["amihud"].iloc[1:].notna().all()
        assert grp["cs_spread"].iloc[1:].notna().all()
        assert (grp["cs_spread"].dropna() >= 0).all()
        assert grp["hl_spread"].notna().all()
        assert grp["abnormal_volume"].iloc[vw + 1:].notna().all()
        assert grp["vix"].notna().all()

    # The synthetic stress window (fixture days 60-80) should show up as
    # elevated vol, elevated VIX, and a wider bond-fund discount.
    spy = panel[panel["ticker"] == "SPY"].reset_index(drop=True)
    assert spy["realized_vol"].iloc[70:80].mean() > spy["realized_vol"].iloc[110:130].mean()
    assert spy["vix"].iloc[60:80].mean() > 2 * spy["vix"].iloc[:60].mean()

    lqd = panel[panel["ticker"] == "LQD"].reset_index(drop=True)
    stress_pd = lqd["premium_discount"].iloc[65:80].mean()
    calm_pd = lqd["premium_discount"].iloc[:60].mean()
    assert stress_pd < calm_pd - 0.005  # discount widens by >50bp in stress

    # Stale-pricing flags exist only for the international fund.
    assert not panel.loc[panel["ticker"] != "EFA", "stale_pricing"].any()

    # Stress layer: fixture dates (2024) are outside every Tier-1 window;
    # Tier-2 VIX flags must exist and fall inside the synthetic stress
    # window (fixture days 60-80).
    panel = add_stress_flags(panel, load_tier1_events(), load_tier2_rules())
    assert list(panel.columns) == PANEL_COLUMNS + STRESS_COLUMNS
    assert not panel["tier1_stress"].any()
    assert panel["vix_stress"].any()
    # The change rule may also catch isolated calm-period jumps, so require
    # the flags to be concentrated in the window rather than exclusive to it.
    spy_flags = panel[panel["ticker"] == "SPY"].reset_index(drop=True)
    flagged_days = spy_flags.index[spy_flags["vix_stress"]]
    in_window = ((flagged_days >= 60) & (flagged_days < 80)).sum()
    assert in_window > len(flagged_days) - in_window
    assert panel["tier2_stress"].sum() >= panel["vix_stress"].sum()

    # Same pipeline through the CLI, writing to a temp file.
    out = tmp_path / "panel.csv"
    assert main(["build-panel", "--mode", "fixture", "--output", str(out)]) == 0
    written = pd.read_csv(out, parse_dates=["date"])
    assert len(written) == len(panel)
    assert list(written.columns) == PANEL_COLUMNS + STRESS_COLUMNS

    # Determinism: in-memory build and CLI-written file agree numerically.
    written["tier1_event"] = written["tier1_event"].astype("string")
    pd.testing.assert_frame_equal(
        written.sort_values(["ticker", "date"]).reset_index(drop=True),
        panel.reset_index(drop=True),
        check_exact=False,
        rtol=1e-12,
    )


def test_event_study_from_fixtures(tmp_path):
    """Panel -> event study -> tables and figures, offline, via the CLI."""
    panel_path = tmp_path / "panel.csv"
    out_dir = tmp_path / "reports"
    assert main(["build-panel", "--mode", "fixture", "--output", str(panel_path)]) == 0

    # The event-study command reads the default panel location, so point it
    # at the freshly written panel by using the default path too.
    settings = load_settings()
    default_panel = settings.panel_dir / "etf_day_panel_fixture.csv"
    default_panel.parent.mkdir(parents=True, exist_ok=True)
    default_panel.write_bytes(panel_path.read_bytes())

    assert main(["event-study", "--mode", "fixture", "--output-dir", str(out_dir)]) == 0

    summary = pd.read_csv(out_dir / "event_summary.csv")
    assert set(summary["ticker"]) == FIXTURE_TICKERS
    assert (summary["event"] == "synthetic_stress_2024").all()

    # Bond funds were built with the widest synthetic stress discounts, so
    # their abnormal dislocation must exceed the domestic-equity fund's.
    by_ticker = summary.set_index("ticker")["min_abnormal_bp"]
    assert by_ticker["HYG"] < by_ticker["LQD"] < by_ticker["SPY"]
    assert by_ticker["HYG"] < -100  # HYG built with a ~200bp stress discount

    windows = pd.read_csv(out_dir / "event_windows.csv")
    es = settings.event_study
    assert len(windows) == len(FIXTURE_TICKERS) * (es.pre_days + es.post_days + 1)

    peaks = pd.read_csv(out_dir / "event_bucket_peaks.csv")
    assert set(peaks["bucket"]) == {
        "domestic_equity", "international_equity", "ig_credit", "hy_credit", "rates",
    }
    assert (out_dir / "event_synthetic_stress_2024.png").is_file()
