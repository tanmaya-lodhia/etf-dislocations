import math

import numpy as np
import pandas as pd
import pytest

from etf_dislocations.analysis.event_study import run_event_study
from etf_dislocations.config import EventStudySettings
from etf_dislocations.stress.tier1_events import StressEvent

CFG = EventStudySettings(
    pre_days=5,
    post_days=10,
    estimation_days=60,
    min_estimation_days=20,
    band_sigma=2.0,
)

N = 100
DATES = pd.bdate_range("2024-01-02", periods=N)
EVENT_START_POS = 70
EVENT = (
    StressEvent(
        "test_event",
        pd.Timestamp(DATES[EVENT_START_POS]),
        pd.Timestamp(DATES[EVENT_START_POS + 10]),
    ),
)


def _panel_with_dislocation(recovery_tau=None):
    """One ticker whose premium/discount is a constant 10bp premium with a
    deterministic +/-5bp alternation (known calm mean and std), then jumps to
    a -200bp discount at the event start, recovering at `recovery_tau`."""
    base = np.full(N, 0.0010)
    base[::2] += 0.0005
    base[1::2] -= 0.0005
    pd_series = base.copy()
    end = EVENT_START_POS + (recovery_tau if recovery_tau is not None else N)
    pd_series[EVENT_START_POS:min(N, end)] = -0.0200
    return pd.DataFrame(
        {
            "date": DATES,
            "ticker": "AAA",
            "bucket": "ig_credit",
            "premium_discount": pd_series,
        }
    )


def test_calm_baseline_and_abnormal_values():
    panel = _panel_with_dislocation(recovery_tau=6)
    out = run_event_study(panel, EVENT, CFG)

    row = out.summary.iloc[0]
    # Calm window is deterministic: mean 10bp, sd of the +/-5bp alternation.
    assert row["calm_mean"] == pytest.approx(0.0010, abs=1e-6)
    assert row["calm_std"] == pytest.approx(0.0005, rel=0.02)
    assert row["n_calm"] == CFG.estimation_days

    # At tau=0 the abnormal dislocation is -200bp - 10bp = -210bp.
    tau0 = out.windows[out.windows["tau"] == 0].iloc[0]
    assert tau0["abnormal_pd"] == pytest.approx(-0.0210, abs=1e-6)
    assert row["min_abnormal"] == pytest.approx(-0.0210, abs=1e-6)


def test_days_to_normalize_matches_recovery():
    out = run_event_study(_panel_with_dislocation(recovery_tau=6), EVENT, CFG)
    # Discount persists for tau 0-5 and recovers into the band at tau=6.
    assert out.summary.iloc[0]["days_to_normalize"] == 6


def test_never_normalizing_is_missing():
    out = run_event_study(_panel_with_dislocation(recovery_tau=None), EVENT, CFG)
    assert math.isnan(out.summary.iloc[0]["days_to_normalize"])


def test_no_dislocation_normalizes_immediately():
    panel = _panel_with_dislocation(recovery_tau=0)  # never leaves the band
    out = run_event_study(panel, EVENT, CFG)
    assert out.summary.iloc[0]["days_to_normalize"] == 0


def test_window_taus_and_shape():
    out = run_event_study(_panel_with_dislocation(recovery_tau=6), EVENT, CFG)
    taus = out.windows["tau"].tolist()
    assert taus == list(range(-CFG.pre_days, CFG.post_days + 1))
    assert (out.windows["band"] > 0).all()


def test_insufficient_calm_history_skipped():
    # Event too early in the sample: fewer than min_estimation_days of calm
    # data before the window, so the only pair is skipped and the study
    # raises rather than reporting a weak baseline.
    early_event = (
        StressEvent("early", pd.Timestamp(DATES[10]), pd.Timestamp(DATES[15])),
    )
    with pytest.raises(ValueError, match="no results"):
        run_event_study(_panel_with_dislocation(), early_event, CFG)


def test_bucket_means_average_across_tickers():
    a = _panel_with_dislocation(recovery_tau=6)
    b = a.copy()
    b["ticker"] = "BBB"
    b["premium_discount"] = b["premium_discount"] * 2  # -400bp discount
    panel = pd.concat([a, b], ignore_index=True)

    out = run_event_study(panel, EVENT, CFG)
    tau0 = out.bucket_means[
        (out.bucket_means["tau"] == 0) & (out.bucket_means["bucket"] == "ig_credit")
    ].iloc[0]
    assert tau0["n_tickers"] == 2
    # Mean of -210bp and -420bp abnormal dislocations.
    expected = (-0.0210 + (-0.0400 - 0.0020)) / 2
    assert tau0["mean_abnormal"] == pytest.approx(expected, abs=1e-5)


def test_duplicate_panel_rows_rejected():
    panel = _panel_with_dislocation()
    dup = pd.concat([panel, panel.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        run_event_study(dup, EVENT, CFG)
