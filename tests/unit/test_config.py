from etf_dislocations.config import load_data_sources, load_settings, repo_root


def test_repo_root_contains_config():
    assert (repo_root() / "config" / "settings.yaml").is_file()
    assert (repo_root() / "config" / "universe.yaml").is_file()


def test_settings_load_and_resolve():
    s = load_settings()
    assert s.fixtures_dir.is_absolute()
    assert s.panel_dir.is_absolute()
    assert s.frozen_dir.is_absolute()
    assert s.liquidity.rolling_window >= 2
    assert s.liquidity.annualisation_days == 252


def test_data_sources_load_stooq_yahoo_and_spdr():
    sources = load_data_sources()
    # Stooq remains the configured default despite being currently blocked
    # by an anti-bot challenge (see docs/live_data_audit.md).
    assert sources.stooq.price_symbols["SPY"] == "spy.us"
    # Yahoo is a fully-specified, documented fallback for every universe
    # ticker (opt-in only, never substituted automatically).
    assert sources.yahoo.price_symbols["SPY"] == "SPY"
    assert sources.yahoo.vix_symbol == "^VIX"
    # SPDR automated NAV is scoped to confirmed State-Street-sponsored
    # tickers only - iShares/Vanguard tickers must not appear here.
    assert sources.spdr_navhist.tickers == {"SPY", "XLF", "XLE", "XLK", "JNK"}
    assert "LQD" not in sources.spdr_navhist.tickers
    assert "{symbol}" in sources.spdr_navhist.url_template
