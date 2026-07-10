import numpy as np
import pandas as pd
import pytest

from etf_dislocations.analysis.event_study import EventStudyOutput
from etf_dislocations.reporting.figures import plot_event_window
from etf_dislocations.reporting.tables import (
    bucket_peak_table,
    event_summary_table,
    write_event_study_tables,
)


def _fake_output():
    windows = pd.DataFrame(
        {
            "event": "ev",
            "ticker": "AAA",
            "bucket": "ig_credit",
            "tau": [-1, 0, 1],
            "date": pd.bdate_range("2024-01-02", periods=3),
            "premium_discount": [0.001, -0.02, -0.01],
            "abnormal_pd": [0.0, -0.021, -0.011],
            "band": 0.001,
        }
    )
    summary = pd.DataFrame(
        {
            "event": ["ev"],
            "ticker": ["AAA"],
            "bucket": ["ig_credit"],
            "n_calm": [60],
            "calm_mean": [0.001],
            "calm_std": [0.0005],
            "min_abnormal": [-0.021],
            "max_abs_abnormal": [0.021],
            "days_to_normalize": [np.nan],
        }
    )
    bucket_means = windows.groupby(
        ["event", "bucket", "tau"], as_index=False
    ).agg(mean_abnormal=("abnormal_pd", "mean"), n_tickers=("ticker", "nunique"))
    return EventStudyOutput(windows, summary, bucket_means)


def test_summary_table_converts_to_basis_points():
    table = event_summary_table(_fake_output().summary)
    assert table["calm_mean_bp"].iloc[0] == pytest.approx(10.0)
    assert table["min_abnormal_bp"].iloc[0] == pytest.approx(-210.0)
    assert "calm_mean" not in table.columns


def test_bucket_peak_table_finds_most_negative_day():
    peaks = bucket_peak_table(_fake_output().bucket_means)
    assert len(peaks) == 1
    assert peaks["peak_tau"].iloc[0] == 0
    assert peaks["peak_mean_abnormal_bp"].iloc[0] == pytest.approx(-210.0)


def test_write_tables_and_figure(tmp_path):
    output = _fake_output()
    written = write_event_study_tables(output, tmp_path)
    assert len(written) == 4
    assert all(p.is_file() for p in written)

    fig_path = plot_event_window(output.bucket_means, "ev", tmp_path / "ev.png")
    assert fig_path.is_file()
    assert fig_path.stat().st_size > 0

    with pytest.raises(ValueError, match="No bucket means"):
        plot_event_window(output.bucket_means, "missing", tmp_path / "x.png")
