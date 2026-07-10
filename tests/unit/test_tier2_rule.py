import numpy as np
import pandas as pd
import pytest

from etf_dislocations.stress.tier2_rule import (
    Tier2Rules,
    load_tier2_rules,
    pd_vol_stress_days,
    vix_stress_days,
)

RULES = Tier2Rules(
    vix_level_percentile=0.95,
    vix_change_percentile=0.95,
    pd_vol_window=5,
    pd_vol_percentile=0.90,
)


def _dates(n):
    return pd.DatetimeIndex(pd.bdate_range("2024-01-02", periods=n))


def test_config_loads_and_validates():
    rules = load_tier2_rules()
    assert 0.5 < rules.vix_level_percentile < 1.0
    assert rules.pd_vol_window >= 2


def test_vix_level_rule_flags_extreme_days():
    # 95 calm days at 12-14, 5 days at 40: the 95th percentile sits below
    # 40, so exactly the elevated days are flagged by the level rule.
    values = np.concatenate([np.linspace(12, 14, 95), np.full(5, 40.0)])
    vix = pd.Series(values, index=_dates(100))
    flags = vix_stress_days(vix, RULES)
    assert flags.iloc[-5:].all()
    assert not flags.iloc[:94].any()


def test_vix_change_rule_flags_spike_day():
    # Flat level with a single one-day jump within the top-5% tail of
    # changes: the jump day is flagged even though the level stays modest.
    values = np.full(100, 15.0)
    values[50] = 19.0
    vix = pd.Series(values, index=_dates(100))
    flags = vix_stress_days(vix, RULES)
    assert bool(flags.iloc[50])
    assert flags.sum() <= 2  # the spike day (and nothing systematic)


def test_pd_vol_rule_flags_volatile_stretch():
    # Premium/discount noise is 10x larger over days 60-80; the flagged days
    # should all sit inside or just after that stretch (rolling window lag).
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 0.0005, 100)
    noise[60:80] = rng.normal(0, 0.005, 20)
    prem = pd.Series(noise, index=_dates(100))
    flags = pd_vol_stress_days(prem, RULES)
    assert flags.any()
    flagged_positions = np.flatnonzero(flags.to_numpy())
    assert flagged_positions.min() >= 60
    assert flagged_positions.max() <= 80 + RULES.pd_vol_window


def test_pd_vol_rule_all_nan_input_never_flags():
    prem = pd.Series(np.nan, index=_dates(30))
    flags = pd_vol_stress_days(prem, RULES)
    assert not flags.any()


def test_bad_percentile_rejected(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "tier2:\n"
        "  vix_level_percentile: 0.3\n"
        "  vix_change_percentile: 0.95\n"
        "  pd_vol_window: 21\n"
        "  pd_vol_percentile: 0.95\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="vix_level_percentile"):
        load_tier2_rules(path)
