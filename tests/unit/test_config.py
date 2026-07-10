from etf_dislocations.config import load_settings, repo_root


def test_repo_root_contains_config():
    assert (repo_root() / "config" / "settings.yaml").is_file()
    assert (repo_root() / "config" / "universe.yaml").is_file()


def test_settings_load_and_resolve():
    s = load_settings()
    assert s.fixtures_dir.is_absolute()
    assert s.panel_dir.is_absolute()
    assert s.liquidity.rolling_window >= 2
    assert s.liquidity.annualisation_days == 252
