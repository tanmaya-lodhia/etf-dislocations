import numpy as np
import pandas as pd
import pytest

from etf_dislocations.analysis.panel_regression import (
    RegressionConfig,
    RegressionSpec,
    load_regression_config,
    prepare_regression_frame,
    run_panel_regressions,
    run_specification,
)

N_TICKERS = 20
N_DAYS = 100


def _synthetic_panel(entity_bias=False, cluster_noise=False, seed=11):
    """Panel with y = 1 + 2*x1 - 3*x2 + noise, known exactly.

    With entity_bias, each ticker gets a fixed intercept shift that is
    correlated with x1, biasing pooled OLS but not fixed-effects estimates.
    With cluster_noise, errors are strongly correlated within each ticker.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=N_DAYS)
    rows = []
    for i in range(N_TICKERS):
        effect = rng.normal(0, 2.0) if entity_bias else 0.0
        x1 = rng.normal(effect if entity_bias else 0.0, 1.0, N_DAYS)
        x2 = rng.normal(0, 1.0, N_DAYS)
        noise = rng.normal(0, 0.05, N_DAYS)
        if cluster_noise:
            noise = noise + rng.normal(0, 1.0)  # common shock per ticker
        y = 1.0 + 2.0 * x1 - 3.0 * x2 + effect + noise
        rows.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "ticker": f"T{i:02d}",
                    "bucket": "ig_credit" if i % 2 else "domestic_equity",
                    "premium_discount": y / 1e4,  # only needed by prepare()
                    "x1": x1,
                    "x2": x2,
                    "y": y,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


POOLED = RegressionSpec("pooled", ("x1", "x2"), False, False)
FE = RegressionSpec("fe", ("x1", "x2"), True, False)


def test_pooled_ols_recovers_known_coefficients():
    frame = prepare_regression_frame(_synthetic_panel())
    coefs, stats = run_specification(frame, POOLED, "y")
    by_var = coefs.set_index("variable")["coef"]
    assert by_var["x1"] == pytest.approx(2.0, abs=0.01)
    assert by_var["x2"] == pytest.approx(-3.0, abs=0.01)
    assert by_var["const"] == pytest.approx(1.0, abs=0.01)
    assert stats["nobs"] == N_TICKERS * N_DAYS
    assert stats["r2_overall"] > 0.99


def test_fixed_effects_remove_entity_bias():
    frame = prepare_regression_frame(_synthetic_panel(entity_bias=True))
    pooled_coef = (
        run_specification(frame, POOLED, "y")[0].set_index("variable")["coef"]
    )
    fe_coef = run_specification(frame, FE, "y")[0].set_index("variable")["coef"]
    # Pooled x1 is biased upward by the correlated entity effect; entity
    # fixed effects recover the true coefficient.
    assert pooled_coef["x1"] > 2.2
    assert fe_coef["x1"] == pytest.approx(2.0, abs=0.02)


def test_clustered_standard_errors_differ_from_unadjusted():
    frame = prepare_regression_frame(_synthetic_panel(cluster_noise=True))
    clustered = run_specification(
        frame, POOLED, "y", cluster_entity=True, cluster_time=False
    )[0].set_index("variable")["std_err"]
    unadjusted = run_specification(
        frame, POOLED, "y", cluster_entity=False, cluster_time=False
    )[0].set_index("variable")["std_err"]
    # Within-ticker common shocks inflate the constant's clustered SE.
    assert clustered["const"] > 2 * unadjusted["const"]


def test_run_is_deterministic():
    frame = prepare_regression_frame(_synthetic_panel())
    a = run_specification(frame, POOLED, "y")[0]
    b = run_specification(frame, POOLED, "y")[0]
    pd.testing.assert_frame_equal(a, b)


def test_prepare_adds_derived_columns():
    panel = _synthetic_panel().assign(tier2_stress=True)
    frame = prepare_regression_frame(panel)
    assert (frame["abs_premium_discount"] >= 0).all()
    assert set(frame["fixed_income"].unique()) == {0.0, 1.0}
    assert (frame["fixed_income_x_stress"] == frame["fixed_income"]).all()
    assert frame.index.names == ["ticker", "date"]


def test_zero_variance_feature_dropped_instead_of_crashing():
    # Reproduces a real degenerate-sample failure found during the
    # live-data audit: a feature that is constant in the complete-case
    # sample (e.g. a stale-pricing flag that is always False for a
    # domestic-only surviving sample) used to collide with the intercept
    # and crash PanelOLS on rank deficiency. It must now be dropped with a
    # warning, and the remaining coefficient still estimated correctly.
    panel = _synthetic_panel()
    panel["zero_var"] = 0.0
    frame = prepare_regression_frame(panel)
    spec = RegressionSpec("degenerate", ("x1", "x2", "zero_var"), False, False)

    coefs, stats = run_specification(frame, spec, "y")
    variables = set(coefs["variable"])
    assert "zero_var" not in variables
    assert {"x1", "x2", "const"} <= variables
    assert coefs.set_index("variable").loc["x1", "coef"] == pytest.approx(2.0, abs=0.02)


def test_all_features_constant_raises():
    panel = _synthetic_panel()
    panel["zero_var"] = 0.0
    frame = prepare_regression_frame(panel)
    spec = RegressionSpec("degenerate", ("zero_var",), False, False)
    with pytest.raises(ValueError, match="all features are constant"):
        run_specification(frame, spec, "y")


def test_entity_effects_with_single_entity_raises_clearly():
    # Reproduces the second real failure found during the live-data audit:
    # a NAV-sparse real-data run where only one ticker survives the
    # complete-case filter. Two-way FE is not estimable there (no
    # cross-sectional heterogeneity to remove) and used to crash inside
    # linearmodels with an opaque "No objects to concatenate" error.
    panel = _synthetic_panel()
    single = panel[panel["ticker"] == "T00"]
    frame = prepare_regression_frame(single)
    spec = RegressionSpec("fe_single", ("x1", "x2"), True, True)
    with pytest.raises(ValueError, match="entity_effects requires at least 2 entities"):
        run_specification(frame, spec, "y")


def test_run_panel_regressions_skips_inestimable_spec():
    panel = _synthetic_panel()
    single = panel[panel["ticker"] == "T00"]
    frame_source = single
    cfg = RegressionConfig(
        dependent="y",
        cluster_entity=True,
        cluster_time=False,
        specifications=(
            RegressionSpec("pooled_ok", ("x1", "x2"), False, False),
            RegressionSpec("fe_broken", ("x1", "x2"), True, True),
        ),
    )
    coefs, stats = run_panel_regressions(frame_source, cfg)
    assert set(stats["spec"]) == {"pooled_ok"}
    assert set(coefs["spec"]) == {"pooled_ok"}


def test_missing_feature_column_raises():
    frame = prepare_regression_frame(_synthetic_panel())
    bad = RegressionSpec("bad", ("nonexistent",), False, False)
    with pytest.raises(ValueError, match="nonexistent"):
        run_specification(frame, bad, "y")


def test_config_loads_and_matches_spec():
    cfg = load_regression_config()
    assert cfg.dependent == "abs_premium_discount"
    assert cfg.cluster_entity and cfg.cluster_time
    names = [s.name for s in cfg.specifications]
    assert names == [
        "pooled_channels",
        "pooled_stress_interaction",
        "two_way_fixed_effects",
    ]
    fe = cfg.specifications[2]
    assert fe.entity_effects and fe.time_effects
    # Market-wide variables must not appear in the time-effects spec.
    assert "vix" not in fe.features
