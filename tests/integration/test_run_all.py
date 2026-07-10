"""Full-pipeline orchestration and reproducibility (SPEC.md sections 6.4,
milestone 10): one command produces the complete output set, and two runs on
the same inputs produce byte-identical CSVs and manifests. Offline.
"""

import json

from etf_dislocations.cli import main

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
