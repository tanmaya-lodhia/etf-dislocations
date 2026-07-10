import numpy as np
import pandas as pd

from etf_dislocations.stress.apply import STRESS_COLUMNS, add_stress_flags
from etf_dislocations.stress.tier1_events import StressEvent
from etf_dislocations.stress.tier2_rule import Tier2Rules

RULES = Tier2Rules(
    vix_level_percentile=0.90,
    vix_change_percentile=0.90,
    pd_vol_window=3,
    pd_vol_percentile=0.90,
)

EVENTS = (
    StressEvent("test_event", pd.Timestamp("2024-01-10"), pd.Timestamp("2024-01-12")),
)


def _mini_panel(n=20):
    dates = pd.bdate_range("2024-01-02", periods=n)
    rng = np.random.default_rng(3)
    frames = []
    for ticker in ["AAA", "BBB"]:
        vix = np.full(n, 14.0)
        vix[-2:] = 40.0  # top-decile VIX days at the end of the sample
        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "ticker": ticker,
                    "premium_discount": rng.normal(0, 0.001, n),
                    "vix": vix,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def test_stress_columns_added_and_typed():
    panel = _mini_panel()
    out = add_stress_flags(panel, EVENTS, RULES)
    assert all(c in out.columns for c in STRESS_COLUMNS)
    assert len(out) == len(panel)
    for col in ["tier1_stress", "vix_stress", "pd_vol_stress", "tier2_stress"]:
        assert out[col].dtype == bool


def test_tier1_flags_inside_window_only():
    out = add_stress_flags(_mini_panel(), EVENTS, RULES)
    in_window = out["date"].between("2024-01-10", "2024-01-12")
    assert out.loc[in_window, "tier1_stress"].all()
    assert (out.loc[in_window, "tier1_event"] == "test_event").all()
    assert not out.loc[~in_window, "tier1_stress"].any()
    assert out.loc[~in_window, "tier1_event"].isna().all()


def test_vix_flags_broadcast_to_all_tickers():
    out = add_stress_flags(_mini_panel(), EVENTS, RULES)
    last_dates = sorted(out["date"].unique())[-2:]
    flagged = out[out["date"].isin(last_dates)]
    assert flagged["vix_stress"].all()
    assert set(flagged["ticker"]) == {"AAA", "BBB"}
    assert not out[~out["date"].isin(last_dates)]["vix_stress"].any()


def test_tier2_is_union_of_component_rules():
    out = add_stress_flags(_mini_panel(), EVENTS, RULES)
    expected = out["vix_stress"] | out["pd_vol_stress"]
    assert (out["tier2_stress"] == expected).all()


def test_missing_vix_never_flags():
    panel = _mini_panel()
    panel["vix"] = np.nan
    out = add_stress_flags(panel, EVENTS, RULES)
    assert not out["vix_stress"].any()
