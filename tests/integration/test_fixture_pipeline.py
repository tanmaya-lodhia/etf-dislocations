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

    # Same pipeline through the CLI, writing to a temp file.
    out = tmp_path / "panel.csv"
    assert main(["build-panel", "--mode", "fixture", "--output", str(out)]) == 0
    written = pd.read_csv(out, parse_dates=["date"])
    assert len(written) == len(panel)
    assert list(written.columns) == PANEL_COLUMNS

    # Determinism: in-memory build and CLI-written file agree numerically.
    pd.testing.assert_frame_equal(
        written.sort_values(["ticker", "date"]).reset_index(drop=True),
        panel.reset_index(drop=True),
        check_exact=False,
        rtol=1e-12,
    )
