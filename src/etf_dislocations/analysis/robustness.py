"""Robustness suite (SPEC.md section 2.11).

Every check perturbs one assumption of the headline analysis and reruns it;
nothing here introduces new estimators. Two families:

Regression variants — rerun the headline panel specification
(pooled_stress_interaction) under:
- baseline: unmodified panel, for side-by-side comparison
- alt_dependent_log: |log premium/discount| as the dependent variable
- alt_spread_hl: high-low range ratio replacing the Corwin-Schultz spread
- tier2_pctl_<q>: Tier-2 stress flags recomputed at alternative percentiles
- exclude_<event>: the named Tier-1 event's window dropped from the sample
- winsorized: dependent winsorised two-sided at the configured share

Placebo event study — the event-study machinery run on randomly drawn
windows that do not overlap any real event, with a fixed seed. If the
methodology is sound, placebo abnormal dislocation is small and normalises
immediately for most pairs; the output reports this rather than asserting it.
"""

from __future__ import annotations

import dataclasses
import logging

import numpy as np
import pandas as pd

from ..config import EventStudySettings, RobustnessSettings
from ..stress.apply import STRESS_COLUMNS, add_stress_flags
from ..stress.tier1_events import StressEvent
from ..stress.tier2_rule import Tier2Rules
from .event_study import run_event_study
from .panel_regression import (
    RegressionConfig,
    RegressionSpec,
    prepare_regression_frame,
    run_specification,
)

logger = logging.getLogger(__name__)

HEADLINE_SPEC = "pooled_stress_interaction"


def winsorize(series: pd.Series, pct: float) -> pd.Series:
    """Two-sided winsorisation at the pct / 1-pct sample quantiles."""
    if not 0 < pct < 0.5:
        raise ValueError(f"pct must be in (0, 0.5), got {pct}")
    lo, hi = series.quantile([pct, 1 - pct])
    return series.clip(lower=lo, upper=hi)


def _headline(reg_cfg: RegressionConfig) -> RegressionSpec:
    for spec in reg_cfg.specifications:
        if spec.name == HEADLINE_SPEC:
            return spec
    logger.warning(
        "No %s specification configured; using %s",
        HEADLINE_SPEC,
        reg_cfg.specifications[0].name,
    )
    return reg_cfg.specifications[0]


def _run_variant(
    variant: str,
    frame: pd.DataFrame,
    spec: RegressionSpec,
    dependent: str,
    reg_cfg: RegressionConfig,
) -> pd.DataFrame:
    # A perturbation can make a feature constant in the remaining sample
    # (e.g. excluding the only stress event zeroes the stress dummy);
    # run_specification() drops such features for this call rather than
    # crashing on a rank-deficient design matrix.
    coefs, stats = run_specification(
        frame,
        spec,
        dependent,
        cluster_entity=reg_cfg.cluster_entity,
        cluster_time=reg_cfg.cluster_time,
    )
    coefs = coefs.drop(columns="spec")
    coefs.insert(0, "variant", variant)
    coefs["nobs"] = stats["nobs"]
    return coefs


def regression_variants(
    panel: pd.DataFrame,
    reg_cfg: RegressionConfig,
    rules: Tier2Rules,
    events: tuple[StressEvent, ...],
    rob: RobustnessSettings,
) -> pd.DataFrame:
    """Run every regression-variant check; returns a tidy coefficient table."""
    spec = _headline(reg_cfg)
    dependent = reg_cfg.dependent
    results = []

    frame = prepare_regression_frame(panel)
    results.append(_run_variant("baseline", frame, spec, dependent, reg_cfg))

    if "log_premium_discount" in panel.columns:
        alt = panel.assign(
            abs_log_premium_discount=panel["log_premium_discount"].abs()
        )
        results.append(
            _run_variant(
                "alt_dependent_log",
                prepare_regression_frame(alt),
                spec,
                "abs_log_premium_discount",
                reg_cfg,
            )
        )
    else:
        logger.warning("No log_premium_discount column; skipping log-dependent check")

    if "cs_spread" in spec.features and "hl_spread" in panel.columns:
        alt_features = tuple(
            "hl_spread" if f == "cs_spread" else f for f in spec.features
        )
        alt_spec = dataclasses.replace(spec, features=alt_features)
        results.append(
            _run_variant("alt_spread_hl", frame, alt_spec, dependent, reg_cfg)
        )

    for pctl in rob.tier2_percentiles:
        alt_rules = dataclasses.replace(
            rules,
            vix_level_percentile=pctl,
            vix_change_percentile=pctl,
            pd_vol_percentile=pctl,
        )
        stripped = panel.drop(
            columns=[c for c in STRESS_COLUMNS if c in panel.columns]
        )
        reflagged = add_stress_flags(stripped, events, alt_rules)
        results.append(
            _run_variant(
                f"tier2_pctl_{int(round(pctl * 100)):03d}",
                prepare_regression_frame(reflagged),
                spec,
                dependent,
                reg_cfg,
            )
        )

    excluded = next((e for e in events if e.name == rob.exclude_event), None)
    if excluded is None:
        logger.warning(
            "Event %r not in the supplied event list; skipping exclusion check",
            rob.exclude_event,
        )
    else:
        keep = ~panel["date"].between(excluded.start, excluded.end)
        results.append(
            _run_variant(
                f"exclude_{excluded.name}",
                prepare_regression_frame(panel.loc[keep]),
                spec,
                dependent,
                reg_cfg,
            )
        )

    wins = frame.copy()
    wins[dependent] = winsorize(wins[dependent], rob.winsor_pct)
    results.append(_run_variant("winsorized", wins, spec, dependent, reg_cfg))

    out = pd.concat(results, ignore_index=True)
    logger.info(
        "Robustness regressions: %d variants (%s)",
        out["variant"].nunique(),
        ", ".join(out["variant"].unique()),
    )
    return out


def draw_placebo_events(
    dates: pd.DatetimeIndex,
    real_events: tuple[StressEvent, ...],
    es_cfg: EventStudySettings,
    n_placebo: int,
    seed: int,
) -> tuple[StressEvent, ...]:
    """Draw placebo event windows from the trading calendar, deterministic
    given the seed. A start date is eligible only if neither its event
    window nor its calm estimation window overlaps a real event: an
    estimation window contaminated by real-event dislocation would shift the
    baseline and manufacture spurious placebo 'dislocations'."""
    dates = pd.DatetimeIndex(sorted(dates.unique()))
    min_start = es_cfg.min_estimation_days + es_cfg.pre_days
    max_start = len(dates) - es_cfg.post_days - 1

    eligible = []
    for i in range(min_start, max_start):
        est_start = dates[max(0, i - es_cfg.pre_days - es_cfg.estimation_days)]
        w_end = dates[i + es_cfg.post_days]
        overlaps = any(
            est_start <= ev.end and ev.start <= w_end for ev in real_events
        )
        if not overlaps:
            eligible.append(i)
    if not eligible:
        raise ValueError("No eligible placebo start dates in the sample")

    rng = np.random.default_rng(seed)
    k = min(n_placebo, len(eligible))
    if k < n_placebo:
        logger.warning("Only %d eligible placebo windows (< %d)", k, n_placebo)
    picks = sorted(rng.choice(eligible, size=k, replace=False).tolist())
    return tuple(
        StressEvent(
            name=f"placebo_{rank:02d}",
            start=dates[i],
            end=dates[min(i + es_cfg.post_days, len(dates) - 1)],
        )
        for rank, i in enumerate(picks)
    )


def placebo_event_study(
    panel: pd.DataFrame,
    real_events: tuple[StressEvent, ...],
    es_cfg: EventStudySettings,
    rob: RobustnessSettings,
) -> pd.DataFrame:
    """Placebo event study; returns the per-(window, ticker) summary."""
    placebos = draw_placebo_events(
        pd.DatetimeIndex(panel["date"]),
        real_events,
        es_cfg,
        rob.n_placebo,
        rob.seed,
    )
    out = run_event_study(panel, placebos, es_cfg)
    summary = out.summary.copy()
    logger.info(
        "Placebo study: %d windows, mean max |abnormal| %.1f bp, "
        "%.0f%% normalised immediately",
        summary["event"].nunique(),
        summary["max_abs_abnormal"].mean() * 1e4,
        100 * (summary["days_to_normalize"] == 0).mean(),
    )
    return summary
