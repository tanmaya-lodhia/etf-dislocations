import pandas as pd
import pytest

from etf_dislocations.config import load_settings
from etf_dislocations.data.loaders import clean_prices, load_fixture_prices


def _raw(rows):
    return pd.DataFrame(
        rows, columns=["date", "open", "high", "low", "close", "volume"]
    )


def test_clean_prices_happy_path():
    raw = _raw(
        [
            ["2024-01-03", 10.0, 10.5, 9.8, 10.2, 1000],
            ["2024-01-02", 9.9, 10.1, 9.7, 10.0, 900],
        ]
    )
    out = clean_prices(raw, "TEST")
    assert list(out.index) == list(pd.to_datetime(["2024-01-02", "2024-01-03"]))
    assert out.loc["2024-01-03", "close"] == 10.2


def test_clean_prices_drops_bad_rows_and_duplicates():
    raw = _raw(
        [
            ["2024-01-02", 10.0, 10.5, 9.8, 10.2, 1000],
            ["2024-01-03", -1.0, 10.1, 9.7, 10.0, 900],  # negative price
            ["2024-01-04", 10.0, 10.1, 9.7, 10.0, -5],  # negative volume
            ["2024-01-05", 10.0, 10.1, 9.7, None, 900],  # missing close
            ["2024-01-08", 10.0, 10.2, 9.9, 10.1, 800],
            ["2024-01-08", 10.0, 10.2, 9.9, 10.3, 850],  # duplicate, keep last
        ]
    )
    out = clean_prices(raw, "TEST")
    assert len(out) == 2
    assert out.loc["2024-01-08", "close"] == 10.3


def test_clean_prices_missing_column_raises():
    raw = pd.DataFrame({"date": ["2024-01-02"], "close": [10.0]})
    with pytest.raises(ValueError, match="missing required columns"):
        clean_prices(raw, "TEST")


def test_clean_prices_all_invalid_raises():
    raw = _raw([["2024-01-02", -1, -1, -1, -1, -1]])
    with pytest.raises(ValueError, match="no valid rows"):
        clean_prices(raw, "TEST")


def test_load_fixture_prices_offline():
    settings = load_settings()
    prices = load_fixture_prices(settings.fixtures_dir)
    assert set(prices) == {"SPY", "EFA", "LQD", "HYG", "TLT"}
    for ticker, df in prices.items():
        assert len(df) == 130, ticker
        assert df.index.is_monotonic_increasing
        assert not df.index.duplicated().any()


def test_load_fixture_prices_missing_ticker_raises():
    settings = load_settings()
    with pytest.raises(FileNotFoundError, match="NOTREAL"):
        load_fixture_prices(settings.fixtures_dir, ["SPY", "NOTREAL"])
