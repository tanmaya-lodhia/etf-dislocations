"""Event study of premium/discount dislocation around stress windows
(SPEC.md section 2.8).

For each (event, ETF) pair:

- The calm baseline is the mean and standard deviation of the daily
  premium/discount over up to `estimation_days` trading days ending just
  before the event window opens.
- Abnormal dislocation on each event-window day is the observed
  premium/discount minus the calm mean; the confidence band is
  +/- band_sigma calm standard deviations around zero.
- Time-to-normalization is the first day at or after the event start on
  which abnormal dislocation is back inside the band (0 if it never left;
  missing if it has not normalised by the end of the window).

Pairs with too little calm history or no trading during the event window are
skipped with a warning rather than silently producing weak baselines.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import EventStudySettings
from ..stress.tier1_events import StressEvent

logger = logging.getLogger(__name__)

REQUIRED_PANEL_COLUMNS = ["date", "ticker", "bucket", "premium_discount"]

WINDOW_COLUMNS = [
    "event",
    "ticker",
    "bucket",
    "tau",
    "date",
    "premium_discount",
    "abnormal_pd",
    "band",
]

SUMMARY_COLUMNS = [
    "event",
    "ticker",
    "bucket",
    "n_calm",
    "calm_mean",
    "calm_std",
    "min_abnormal",
    "max_abs_abnormal",
    "days_to_normalize",
]


@dataclass(frozen=True)
class EventStudyOutput:
    windows: pd.DataFrame       # one row per (event, ticker, tau)
    summary: pd.DataFrame       # one row per (event, ticker)
    bucket_means: pd.DataFrame  # one row per (event, bucket, tau)


def _validate_panel(panel: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_PANEL_COLUMNS if c not in panel.columns]
    if missing:
        raise ValueError(f"Panel is missing required columns: {missing}")
    if panel.duplicated(subset=["ticker", "date"]).any():
        raise ValueError("Panel has duplicate (ticker, date) rows")


def _study_one(
    sub: pd.DataFrame,
    event: StressEvent,
    cfg: EventStudySettings,
) -> tuple[pd.DataFrame, dict] | None:
    """Event-window frame and summary row for one ticker, or None to skip."""
    ticker = sub["ticker"].iloc[0]
    dates = sub["date"]

    at_or_after = np.flatnonzero(dates.to_numpy() >= event.start.to_datetime64())
    if len(at_or_after) == 0 or dates.iloc[at_or_after[0]] > event.end:
        logger.warning("%s/%s: no trading data in event window", event.name, ticker)
        return None
    p0 = int(at_or_after[0])

    est_end = p0 - cfg.pre_days
    est_start = max(0, est_end - cfg.estimation_days)
    calm = sub["premium_discount"].iloc[max(0, est_start):max(0, est_end)].dropna()
    if len(calm) < cfg.min_estimation_days:
        logger.warning(
            "%s/%s: only %d calm observations (< %d), skipping",
            event.name, ticker, len(calm), cfg.min_estimation_days,
        )
        return None
    calm_mean = float(calm.mean())
    calm_std = float(calm.std(ddof=1))
    band = cfg.band_sigma * calm_std

    w_start = max(0, p0 - cfg.pre_days)
    w_end = min(len(sub), p0 + cfg.post_days + 1)
    window = sub.iloc[w_start:w_end]
    tau = np.arange(w_start, w_end) - p0
    abnormal = window["premium_discount"].to_numpy() - calm_mean

    frame = pd.DataFrame(
        {
            "event": event.name,
            "ticker": ticker,
            "bucket": window["bucket"].to_numpy(),
            "tau": tau,
            "date": window["date"].to_numpy(),
            "premium_discount": window["premium_discount"].to_numpy(),
            "abnormal_pd": abnormal,
            "band": band,
        }
    )

    post = frame[frame["tau"] >= 0]
    inside = post["abnormal_pd"].abs() <= band
    normalized = post.loc[inside & post["abnormal_pd"].notna(), "tau"]
    days_to_normalize = float(normalized.iloc[0]) if len(normalized) else np.nan

    summary = {
        "event": event.name,
        "ticker": ticker,
        "bucket": window["bucket"].iloc[0],
        "n_calm": len(calm),
        "calm_mean": calm_mean,
        "calm_std": calm_std,
        "min_abnormal": float(np.nanmin(abnormal)),
        "max_abs_abnormal": float(np.nanmax(np.abs(abnormal))),
        "days_to_normalize": days_to_normalize,
    }
    return frame, summary


def run_event_study(
    panel: pd.DataFrame,
    events: tuple[StressEvent, ...],
    cfg: EventStudySettings,
) -> EventStudyOutput:
    """Run the event study for every (event, ticker) pair in the panel."""
    _validate_panel(panel)

    frames: list[pd.DataFrame] = []
    summaries: list[dict] = []
    for event in events:
        for _, sub in panel.sort_values("date").groupby("ticker", sort=True):
            result = _study_one(sub.reset_index(drop=True), event, cfg)
            if result is not None:
                frames.append(result[0])
                summaries.append(result[1])

    if not frames:
        raise ValueError(
            "Event study produced no results: no (event, ticker) pair had "
            "both event-window data and a sufficient calm baseline"
        )

    windows = pd.concat(frames, ignore_index=True).loc[:, WINDOW_COLUMNS]
    summary = pd.DataFrame(summaries).loc[:, SUMMARY_COLUMNS]

    bucket_means = (
        windows.groupby(["event", "bucket", "tau"], as_index=False)
        .agg(
            mean_abnormal=("abnormal_pd", "mean"),
            n_tickers=("ticker", "nunique"),
        )
    )

    logger.info(
        "Event study: %d (event, ticker) pairs, %d window rows",
        len(summary),
        len(windows),
    )
    return EventStudyOutput(
        windows=windows, summary=summary, bucket_means=bucket_means
    )
