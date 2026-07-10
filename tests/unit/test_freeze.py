import pandas as pd
import pytest

from etf_dislocations.freeze import build_provenance, freeze_panel, load_frozen_panel


def _panel():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"]
            ),
            "ticker": ["AAA", "AAA", "BBB", "BBB"],
            "close": [10.0, 10.5, 20.0, 20.5],
        }
    )


def test_build_provenance_summarises_panel():
    prov = build_provenance(
        _panel(), mode="public", price_source="yahoo", retrieved="2026-07-12"
    )
    assert prov.dataset == "etf_day_panel"
    assert prov.tickers == ("AAA", "BBB")
    assert prov.date_range == ("2024-01-02", "2024-01-03")
    assert prov.n_rows == 4
    assert prov.retrieved == "2026-07-12"


def test_build_provenance_rejects_empty_panel():
    with pytest.raises(ValueError, match="empty panel"):
        build_provenance(_panel().iloc[:0], mode="public", price_source="yahoo",
                          retrieved="2026-07-12")


def test_freeze_and_load_round_trip(tmp_path):
    panel = _panel()
    prov = build_provenance(panel, mode="public", price_source="yahoo",
                             retrieved="2026-07-12", notes="test snapshot")
    parquet_path, provenance_path = freeze_panel(panel, tmp_path, prov, name="test_snap")

    assert parquet_path.name == "test_snap.parquet"
    assert provenance_path.name == "test_snap.provenance.json"

    loaded_panel, loaded_prov = load_frozen_panel(parquet_path)
    pd.testing.assert_frame_equal(loaded_panel, panel)
    assert loaded_prov["price_source"] == "yahoo"
    assert loaded_prov["notes"] == "test snapshot"
    assert loaded_prov["tickers"] == ["AAA", "BBB"]


def test_freeze_refuses_to_overwrite_without_force(tmp_path):
    panel = _panel()
    prov = build_provenance(panel, mode="public", price_source="yahoo",
                             retrieved="2026-07-12")
    freeze_panel(panel, tmp_path, prov, name="test_snap")
    with pytest.raises(FileExistsError, match="already exists"):
        freeze_panel(panel, tmp_path, prov, name="test_snap")


def test_freeze_force_replaces_existing_snapshot(tmp_path):
    panel = _panel()
    prov1 = build_provenance(panel, mode="public", price_source="yahoo",
                              retrieved="2026-07-12")
    freeze_panel(panel, tmp_path, prov1, name="test_snap")

    updated = panel.copy()
    updated["close"] = updated["close"] * 2
    prov2 = build_provenance(updated, mode="public", price_source="yahoo",
                              retrieved="2026-07-13")
    freeze_panel(updated, tmp_path, prov2, name="test_snap", force=True)

    loaded_panel, loaded_prov = load_frozen_panel(tmp_path / "test_snap.parquet")
    assert loaded_prov["retrieved"] == "2026-07-13"
    pd.testing.assert_frame_equal(loaded_panel, updated)


def test_freeze_default_name_uses_retrieved_date(tmp_path):
    panel = _panel()
    prov = build_provenance(panel, mode="public", price_source="yahoo",
                             retrieved="2026-07-12")
    parquet_path, _ = freeze_panel(panel, tmp_path, prov)
    assert parquet_path.name == "etf_panel_2026-07-12.parquet"


def test_load_frozen_panel_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        load_frozen_panel(tmp_path / "missing.parquet")


def test_load_frozen_panel_missing_provenance_raises(tmp_path):
    panel = _panel()
    panel.to_parquet(tmp_path / "orphan.parquet", index=False)
    with pytest.raises(FileNotFoundError, match="Provenance record not found"):
        load_frozen_panel(tmp_path / "orphan.parquet")
