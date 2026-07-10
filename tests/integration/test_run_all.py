"""Full-pipeline orchestration and reproducibility (SPEC.md sections 6.4,
milestone 10): one command produces the complete output set, and two runs on
the same inputs produce byte-identical CSVs and manifests. Offline.
"""

import json

import pandas as pd
import pytest

from etf_dislocations.cli import main
from etf_dislocations.config import load_settings
from etf_dislocations.freeze import load_frozen_panel

EXPECTED_OUTPUTS = {
    "event_windows.csv",
    "event_summary.csv",
    "event_bucket_means.csv",
    "event_bucket_peaks.csv",
    "event_synthetic_stress_2024.png",
    "regression_coefficients.csv",
    "regression_stats.csv",
    "mean_reversion_half_lives.csv",
    "mean_reversion_regime_tests.csv",
    "robustness_regressions.csv",
    "robustness_placebo.csv",
    "run_manifest.json",
}


def _run(out_dir):
    assert main(["run-all", "--mode", "fixture", "--output-dir", str(out_dir)]) == 0
    return {p.name: p for p in out_dir.iterdir() if p.is_file()}


def test_run_all_produces_complete_output_set(tmp_path):
    outputs = _run(tmp_path / "run1")
    assert set(outputs) == EXPECTED_OUTPUTS

    manifest = json.loads(outputs["run_manifest.json"].read_text())
    assert manifest["mode"] == "fixture"
    listed = {e["file"] for e in manifest["outputs"]}
    assert listed == EXPECTED_OUTPUTS - {"run_manifest.json"}
    for entry in manifest["outputs"]:
        if entry["file"].endswith(".csv"):
            assert entry["rows"] > 0

    # The fixture-mode robustness run must include the exclusion check,
    # auto-targeted at the synthetic fixture event.
    rob = (tmp_path / "run1" / "robustness_regressions.csv").read_text()
    assert "exclude_synthetic_stress_2024" in rob


def test_run_all_is_reproducible(tmp_path):
    first = _run(tmp_path / "run1")
    second = _run(tmp_path / "run2")
    assert set(first) == set(second)
    for name in first:
        if name.endswith(".png"):
            continue  # image encoding is not part of the guarantee
        assert first[name].read_bytes() == second[name].read_bytes(), name


def test_freeze_snapshots_a_built_panel(tmp_path):
    settings = load_settings()
    default_panel = settings.panel_dir / "etf_day_panel_fixture.csv"
    if not default_panel.is_file():
        assert main(["build-panel", "--mode", "fixture"]) == 0

    out_dir = tmp_path / "frozen"
    assert main([
        "freeze", "--mode", "fixture", "--price-source", "fixture",
        "--name", "test_snapshot", "--notes", "integration test",
        "--output-dir", str(out_dir),
    ]) == 0

    panel, provenance = load_frozen_panel(out_dir / "test_snapshot.parquet")
    original = pd.read_csv(default_panel, parse_dates=["date"])
    assert len(panel) == len(original)
    assert provenance["mode"] == "fixture"
    assert provenance["price_source"] == "fixture"
    assert provenance["notes"] == "integration test"
    assert provenance["n_rows"] == len(original)

    # A second freeze of the same name must refuse to overwrite silently.
    with pytest.raises(FileExistsError, match="already exists"):
        main([
            "freeze", "--mode", "fixture", "--price-source", "fixture",
            "--name", "test_snapshot", "--output-dir", str(out_dir),
        ])
