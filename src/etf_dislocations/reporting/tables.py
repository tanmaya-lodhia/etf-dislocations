"""Publication-oriented tables from analysis result objects.

No analysis logic here: functions take the result frames produced by the
analysis modules and reshape or persist them. Values are kept numeric (basis
points where noted) so downstream formatting stays flexible.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..analysis.event_study import EventStudyOutput

logger = logging.getLogger(__name__)


def event_summary_table(summary: pd.DataFrame) -> pd.DataFrame:
    """Per-(event, ticker) summary with dislocation stats in basis points."""
    out = summary.copy()
    for col in ["calm_mean", "calm_std", "min_abnormal", "max_abs_abnormal"]:
        out[f"{col}_bp"] = out[col] * 1e4
        out = out.drop(columns=col)
    return out


def bucket_peak_table(bucket_means: pd.DataFrame) -> pd.DataFrame:
    """Peak average dislocation per (event, bucket): the most negative mean
    abnormal premium/discount over the event window, in basis points, and
    the day it occurred."""
    idx = bucket_means.groupby(["event", "bucket"])["mean_abnormal"].idxmin()
    peak = bucket_means.loc[idx, ["event", "bucket", "tau", "mean_abnormal"]]
    peak = peak.rename(
        columns={"tau": "peak_tau", "mean_abnormal": "peak_mean_abnormal"}
    )
    peak["peak_mean_abnormal_bp"] = peak.pop("peak_mean_abnormal") * 1e4
    return peak.reset_index(drop=True)


def write_regression_tables(
    coefficients: pd.DataFrame, stats: pd.DataFrame, out_dir: Path
) -> list[Path]:
    """Persist panel-regression outputs as CSVs; returns written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, frame in [
        ("regression_coefficients", coefficients),
        ("regression_stats", stats),
    ]:
        path = out_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        written.append(path)
        logger.info("Wrote %s (%d rows)", path, len(frame))
    return written


def write_mean_reversion_tables(
    half_lives: pd.DataFrame, regime_tests: pd.DataFrame, out_dir: Path
) -> list[Path]:
    """Persist mean-reversion outputs as CSVs; returns written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, frame in [
        ("mean_reversion_half_lives", half_lives),
        ("mean_reversion_regime_tests", regime_tests),
    ]:
        path = out_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        written.append(path)
        logger.info("Wrote %s (%d rows)", path, len(frame))
    return written


def write_robustness_tables(
    regressions: pd.DataFrame, placebo: pd.DataFrame, out_dir: Path
) -> list[Path]:
    """Persist robustness-suite outputs as CSVs; returns written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, frame in [
        ("robustness_regressions", regressions),
        ("robustness_placebo", placebo),
    ]:
        path = out_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        written.append(path)
        logger.info("Wrote %s (%d rows)", path, len(frame))
    return written


def write_event_study_tables(output: EventStudyOutput, out_dir: Path) -> list[Path]:
    """Persist the event-study result set as CSVs; returns written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, frame in [
        ("event_windows", output.windows),
        ("event_summary", event_summary_table(output.summary)),
        ("event_bucket_means", output.bucket_means),
        ("event_bucket_peaks", bucket_peak_table(output.bucket_means)),
    ]:
        path = out_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        written.append(path)
        logger.info("Wrote %s (%d rows)", path, len(frame))
    return written
