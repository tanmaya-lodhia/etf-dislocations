import numpy as np
import pandas as pd
import pytest

from etf_dislocations.analysis.robustness import (
    draw_placebo_events,
    placebo_event_study,
    regression_variants,
    winsorize,
)
from etf_dislocations.config import EventStudySettings, RobustnessSettings
from etf_dislocations.analysis.panel_regression import (
    RegressionConfig,
    RegressionSpec,
)
from etf_dislocations.stress.tier1_events import StressEvent
from etf_dislocations.stress.tier2_rule import Tier2Rules

N = 250
DATES = pd.bdate_range("2023-01-02", periods=N)

ES_CFG = EventStudySettings(
    pre_days=5, post_days=10, estimation_days=60,
    min_estimation_days=20, band_sigma=1.96,
)
ROB = RobustnessSettings(
    seed=42, n_placebo=5, tier2_percentiles=(0.90,),
    winsor_pct=0.05, exclude_event="real_event",
)
RULES = Tier2Rules(
    vix_level_percentile=0.95, vix_change_percentile=0.95,
    pd_vol_window=21, pd_vol_percentile=0.95,
)
EVENT = StressEvent(
    "real_event", pd.Timestamp(DATES[150]), pd.Timestamp(DATES[160])
)
REG_CFG = RegressionConfig(
    dependent="abs_premium_discount",
    cluster_entity=True,
    cluster_time=False,
    specifications=(
        RegressionSpec(
            "pooled_stress_interaction",
            ("cs_spread", "vix", "tier2_stress", "fixed_income_x_stress"),
            False,
            False,
        ),
    ),
)


def _panel(seed=4):
    rng = np.random.default_rng(seed)
    frames = []
    for i, (ticker, bucket) in enumerate(
        [("AAA", "domestic_equity"), ("BBB", "ig_credit")]
    ):
        pd_series = rng.normal(0, 0.001, N)
        pd_series[150:161] -= 0.01 * (i + 1)  # dislocation in the real event
        vix = np.full(N, 14.0) + rng.normal(0, 1, N)
        vix[150:161] = 35.0
        frames.append(
            pd.DataFrame(
                {
                    "date": DATES,
                    "ticker": ticker,
                    "bucket": bucket,
                    "premium_discount": pd_series,
                    "log_premium_discount": np.log1p(pd_series),
                    "cs_spread": np.abs(rng.normal(0.001, 0.0002, N)),
                    "hl_spread": np.abs(rng.normal(0.002, 0.0004, N)),
                    "vix": vix,
                    "tier2_stress": np.concatenate(
                        [np.zeros(150), np.ones(11), np.zeros(N - 161)]
                    ).astype(bool),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def test_winsorize_clips_tails():
    s = pd.Series(np.arange(100, dtype=float))
    w = winsorize(s, 0.05)
    assert w.min() == s.quantile(0.05)
    assert w.max() == s.quantile(0.95)
    assert (w.iloc[10:90] == s.iloc[10:90]).all()
    with pytest.raises(ValueError):
        winsorize(s, 0.7)


def test_placebo_windows_avoid_real_event_and_are_deterministic():
    placebos = draw_placebo_events(
        pd.DatetimeIndex(DATES), (EVENT,), ES_CFG, n_placebo=5, seed=42
    )
    assert len(placebos) == 5
    for p in placebos:
        window_start = p.start - pd.Timedelta(days=0)
        assert not (window_start <= EVENT.end and EVENT.start <= p.end)
    again = draw_placebo_events(
        pd.DatetimeIndex(DATES), (EVENT,), ES_CFG, n_placebo=5, seed=42
    )
    assert [p.start for p in placebos] == [p.start for p in again]


def test_placebo_study_finds_no_dislocation():
    summary = placebo_event_study(_panel(), (EVENT,), ES_CFG, ROB)
    # Calm noise is 10bp sd, so the max |abnormal| over a 16-day window is
    # of order 2 sd (~20bp) - far below the 100/200bp real-event
    # dislocations, which would push this mean above 100bp.
    assert summary["max_abs_abnormal"].mean() < 0.004
    assert (summary["days_to_normalize"] == 0).mean() > 0.7


def test_regression_variants_present_and_wellformed():
    out = regression_variants(_panel(), REG_CFG, RULES, (EVENT,), ROB)
    variants = set(out["variant"])
    assert variants == {
        "baseline",
        "alt_dependent_log",
        "alt_spread_hl",
        "tier2_pctl_090",
        "exclude_real_event",
        "winsorized",
    }
    assert out["std_err"].gt(0).all()
    assert out["nobs"].gt(0).all()
    # The spread substitution actually happened.
    hl_rows = out[out["variant"] == "alt_spread_hl"]
    assert "hl_spread" in set(hl_rows["variable"])
    assert "cs_spread" not in set(hl_rows["variable"])


def test_exclusion_variant_drops_event_rows():
    out = regression_variants(_panel(), REG_CFG, RULES, (EVENT,), ROB)
    nobs = out.drop_duplicates("variant").set_index("variant")["nobs"]
    assert nobs["exclude_real_event"] == nobs["baseline"] - 2 * 11


def test_unknown_exclude_event_skipped_gracefully():
    import dataclasses

    rob = dataclasses.replace(ROB, exclude_event="not_a_real_event")
    out = regression_variants(_panel(), REG_CFG, RULES, (EVENT,), rob)
    assert not any(v.startswith("exclude_") for v in out["variant"].unique())
