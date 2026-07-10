"""Tier-2 rule-based stress-day flagging (SPEC.md section 2.7).

A day is a stress day when the VIX level or its one-day change is in the top
tail of the sample, or when the ETF's own rolling premium/discount volatility
is in the top tail of that ETF's sample. All thresholds come from
config/stress_rules.yaml, fixed before estimation; given the same inputs and
config the flags are fully deterministic.

Thresholds are in-sample quantiles by construction, which is fine for
descriptive panel work but means flags must be recomputed if the sample
period changes; this is a feature (reproducibility), not a bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from ..config import repo_root


@dataclass(frozen=True)
class Tier2Rules:
    vix_level_percentile: float
    vix_change_percentile: float
    pd_vol_window: int
    pd_vol_percentile: float


def load_tier2_rules(path: Path | None = None) -> Tier2Rules:
    """Load and validate the Tier-2 thresholds."""
    if path is None:
        path = repo_root() / "config" / "stress_rules.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)["tier2"]

    rules = Tier2Rules(
        vix_level_percentile=float(cfg["vix_level_percentile"]),
        vix_change_percentile=float(cfg["vix_change_percentile"]),
        pd_vol_window=int(cfg["pd_vol_window"]),
        pd_vol_percentile=float(cfg["pd_vol_percentile"]),
    )
    for name in ("vix_level_percentile", "vix_change_percentile", "pd_vol_percentile"):
        value = getattr(rules, name)
        if not 0.5 < value < 1.0:
            raise ValueError(f"{name} must be in (0.5, 1), got {value}")
    if rules.pd_vol_window < 2:
        raise ValueError(f"pd_vol_window must be >= 2, got {rules.pd_vol_window}")
    return rules


def vix_stress_days(vix: pd.Series, rules: Tier2Rules) -> pd.Series:
    """True on days when the VIX level or one-day change is in the top tail.

    Quantiles are computed over the full input sample.
    """
    level_threshold = vix.quantile(rules.vix_level_percentile)
    change = vix.diff()
    change_threshold = change.quantile(rules.vix_change_percentile)
    flags = (vix > level_threshold) | (change > change_threshold)
    return flags.rename("vix_stress")


def pd_vol_stress_days(premium_discount: pd.Series, rules: Tier2Rules) -> pd.Series:
    """True on days when one ETF's rolling premium/discount volatility is in
    the top tail of its own sample.

    The rolling window needs to fill before any day can be flagged; days with
    no premium/discount data are never flagged.
    """
    roll_vol = premium_discount.rolling(
        rules.pd_vol_window, min_periods=rules.pd_vol_window
    ).std(ddof=1)
    threshold = roll_vol.quantile(rules.pd_vol_percentile)
    if pd.isna(threshold):
        return pd.Series(False, index=premium_discount.index, name="pd_vol_stress")
    return (roll_vol > threshold).fillna(False).rename("pd_vol_stress")
