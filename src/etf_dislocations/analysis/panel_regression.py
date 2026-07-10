"""Panel regression of dislocation magnitude on channel variables
(SPEC.md section 2.9).

Specifications are fixed in config/regression_spec.yaml before estimation:
this module only executes them. Estimation uses linearmodels.PanelOLS with
two-way clustered standard errors (by ETF and by date) as the default
covariance, and entity/time fixed effects where the specification asks for
them.

Derived columns added by prepare_regression_frame:

- abs_premium_discount: |premium_discount|, the dependent variable
- fixed_income: 1.0 for ig_credit / hy_credit buckets
- fixed_income_x_stress: fixed_income * tier2_stress

Rows with a missing dependent value or missing features are dropped per
specification (rolling windows and NAV gaps make some missingness
structural); the per-spec observation count is reported alongside the
coefficients so sample differences stay visible.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from ..config import repo_root

logger = logging.getLogger(__name__)

FIXED_INCOME_BUCKETS = {"ig_credit", "hy_credit"}


@dataclass(frozen=True)
class RegressionSpec:
    name: str
    features: tuple[str, ...]
    entity_effects: bool
    time_effects: bool


@dataclass(frozen=True)
class RegressionConfig:
    dependent: str
    cluster_entity: bool
    cluster_time: bool
    specifications: tuple[RegressionSpec, ...]


def load_regression_config(path: Path | None = None) -> RegressionConfig:
    """Load and validate the fixed regression specifications."""
    if path is None:
        path = repo_root() / "config" / "regression_spec.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)["regression"]

    specs = []
    seen: set[str] = set()
    for item in cfg["specifications"]:
        name = str(item["name"])
        if name in seen:
            raise ValueError(f"Duplicate specification name: {name}")
        seen.add(name)
        features = tuple(str(x) for x in item["features"])
        if not features:
            raise ValueError(f"Specification {name} has no features")
        specs.append(
            RegressionSpec(
                name=name,
                features=features,
                entity_effects=bool(item["entity_effects"]),
                time_effects=bool(item["time_effects"]),
            )
        )
    if not specs:
        raise ValueError("No regression specifications configured")

    return RegressionConfig(
        dependent=str(cfg["dependent"]),
        cluster_entity=bool(cfg["cluster"]["entity"]),
        cluster_time=bool(cfg["cluster"]["time"]),
        specifications=tuple(specs),
    )


def prepare_regression_frame(panel: pd.DataFrame) -> pd.DataFrame:
    """Add derived columns and set the (ticker, date) MultiIndex that
    linearmodels expects. Boolean columns become floats."""
    required = {"ticker", "date", "bucket", "premium_discount"}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"Panel is missing required columns: {sorted(missing)}")

    out = panel.copy()
    out["abs_premium_discount"] = out["premium_discount"].abs()
    out["fixed_income"] = out["bucket"].isin(FIXED_INCOME_BUCKETS).astype(float)
    if "tier2_stress" in out.columns:
        out["fixed_income_x_stress"] = (
            out["fixed_income"] * out["tier2_stress"].astype(float)
        )
    for col in out.columns:
        if out[col].dtype == bool:
            out[col] = out[col].astype(float)
    return out.set_index(["ticker", "date"]).sort_index()


def run_specification(
    frame: pd.DataFrame,
    spec: RegressionSpec,
    dependent: str,
    cluster_entity: bool = True,
    cluster_time: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """Estimate one specification; returns (coefficient table, fit stats).

    A constant is included for pooled specifications; with fixed effects the
    constant is absorbed and omitted. If the complete-case sample leaves a
    feature with no variance (e.g. a sparse real-data run where dropping
    rows with a missing dependent value happens to leave only entities for
    which that feature never varies - a domestic ticker's stale_pricing flag
    is always zero, say), that feature is dropped with a warning rather than
    handed to the solver, which would otherwise fail on a rank-deficient
    design matrix.
    """
    from linearmodels.panel import PanelOLS

    missing = [c for c in (dependent, *spec.features) if c not in frame.columns]
    if missing:
        raise ValueError(f"{spec.name}: columns not in frame: {missing}")

    cols = [dependent, *spec.features]
    data = frame.loc[:, cols].dropna()
    if data.empty:
        raise ValueError(f"{spec.name}: no complete observations")

    constant = [f for f in spec.features if data[f].nunique() <= 1]
    if constant:
        logger.warning(
            "%s: dropping zero-variance features in this sample: %s",
            spec.name, constant,
        )
        spec = dataclasses.replace(
            spec, features=tuple(f for f in spec.features if f not in constant)
        )
        if not spec.features:
            raise ValueError(f"{spec.name}: all features are constant")

    n_entities = data.index.get_level_values(0).nunique()
    n_periods = data.index.get_level_values(1).nunique()
    if spec.entity_effects and n_entities < 2:
        raise ValueError(
            f"{spec.name}: entity_effects requires at least 2 entities in "
            f"the complete-case sample, got {n_entities} (a single entity "
            f"has no cross-sectional heterogeneity to remove)"
        )
    if spec.time_effects and n_periods < 2:
        raise ValueError(
            f"{spec.name}: time_effects requires at least 2 time periods in "
            f"the complete-case sample, got {n_periods}"
        )

    exog = data[list(spec.features)]
    if not (spec.entity_effects or spec.time_effects):
        exog = exog.assign(const=1.0)

    model = PanelOLS(
        data[dependent],
        exog,
        entity_effects=spec.entity_effects,
        time_effects=spec.time_effects,
    )
    if cluster_entity or cluster_time:
        fit = model.fit(
            cov_type="clustered",
            cluster_entity=cluster_entity,
            cluster_time=cluster_time,
        )
    else:
        fit = model.fit(cov_type="unadjusted")

    coefs = pd.DataFrame(
        {
            "spec": spec.name,
            "variable": fit.params.index,
            "coef": fit.params.to_numpy(),
            "std_err": fit.std_errors.to_numpy(),
            "tstat": fit.tstats.to_numpy(),
            "pvalue": fit.pvalues.to_numpy(),
        }
    )
    stats = {
        "spec": spec.name,
        "nobs": int(fit.nobs),
        "n_entities": int(data.index.get_level_values(0).nunique()),
        "r2_overall": float(fit.rsquared_overall),
        "r2_within": float(fit.rsquared_within),
        "entity_effects": spec.entity_effects,
        "time_effects": spec.time_effects,
    }
    logger.info(
        "%s: %d obs, %d entities, overall R2 %.3f",
        spec.name, stats["nobs"], stats["n_entities"], stats["r2_overall"],
    )
    return coefs, stats


def run_panel_regressions(
    panel: pd.DataFrame, cfg: RegressionConfig
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run every configured specification on the panel.

    Returns a tidy coefficient table (one row per spec-variable) and a fit
    statistics table (one row per spec). A specification that is not
    estimable in this sample (e.g. fixed effects requested with too few
    entities/time periods once incomplete rows are dropped - expected in a
    NAV-data-sparse real-data run) is skipped with a warning rather than
    aborting the whole run; every other specification still runs and reports.
    """
    frame = prepare_regression_frame(panel)
    coef_tables = []
    stat_rows = []
    for spec in cfg.specifications:
        try:
            coefs, stats = run_specification(
                frame,
                spec,
                cfg.dependent,
                cluster_entity=cfg.cluster_entity,
                cluster_time=cfg.cluster_time,
            )
        except ValueError as exc:
            logger.warning("%s: skipped - %s", spec.name, exc)
            continue
        coef_tables.append(coefs)
        stat_rows.append(stats)

    if not coef_tables:
        raise ValueError(
            "No regression specification was estimable on this sample"
        )
    return pd.concat(coef_tables, ignore_index=True), pd.DataFrame(stat_rows)
