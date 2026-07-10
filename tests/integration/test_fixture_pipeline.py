"""End-to-end fixture-mode pipeline test. Runs completely offline:
fixtures -> load -> clean -> panel -> liquidity metrics -> output CSV.
"""

import pandas as pd

from etf_dislocations.cli import main
from etf_dislocations.config import load_settings
from etf_dislocations.data.loaders import load_fixture_prices
from etf_dislocations.panel import PANEL_COLUMNS, build_panel
from etf_dislocations.universe import load_universe

FIXTURE_TICKERS = {"SPY", "EFA", "LQD", "HYG", "TLT"}


def test_full_pipeline_from_fixtures(tmp_path):
    settings = load_settings()
    universe = load_universe()

    prices = load_fixture_prices(settings.fixtures_dir)
    panel = build_panel(prices, universe, settings.liquidity)

    # Shape: 5 tickers x 130 fixture days, one row per ETF-day.
    assert set(panel["ticker"]) == FIXTURE_TICKERS
    assert len(panel) == 5 * 130
    assert list(panel.columns) == PANEL_COLUMNS
    assert not panel.duplicated(subset=["ticker", "date"]).any()

    # Liquidity metrics populated once rolling windows fill.
    w = settings.liquidity.rolling_window
    for _, grp in panel.groupby("ticker"):
        assert grp["dollar_volume"].notna().all()
        assert grp["ret"].iloc[1:].notna().all()
        assert grp["realized_vol"].iloc[w:].notna().all()
        assert grp["amihud"].iloc[1:].notna().all()
        assert (grp["realized_vol"].dropna() > 0).all()
        assert (grp["amihud"].dropna() >= 0).all()

    # The synthetic stress window (fixture days 60-80) should show up as
    # elevated realised vol relative to the calm tail of the sample.
    spy = panel[panel["ticker"] == "SPY"].reset_index(drop=True)
    stress_vol = spy["realized_vol"].iloc[70:80].mean()
    calm_vol = spy["realized_vol"].iloc[110:130].mean()
    assert stress_vol > calm_vol

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
