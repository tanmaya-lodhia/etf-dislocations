import numpy as np
import pandas as pd
import pytest

from etf_dislocations.config import LiquiditySettings
from etf_dislocations.panel import PANEL_COLUMNS, build_panel
from etf_dislocations.universe import EtfEntry, Universe

LIQ = LiquiditySettings(rolling_window=3, annualisation_days=252)

UNIVERSE = Universe(
    (
        EtfEntry("AAA", "domestic_equity"),
        EtfEntry("BBB", "hy_credit"),
    )
)


def _prices(n=6, start_price=100.0, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=n)
    close = start_price * np.cumprod(1 + rng.normal(0, 0.01, n))
    df = pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(1000, 5000, n).astype(float),
        },
        index=pd.DatetimeIndex(dates, name="date"),
    )
    return df


def test_panel_shape_columns_and_keys():
    prices = {"AAA": _prices(seed=1), "BBB": _prices(seed=2)}
    panel = build_panel(prices, UNIVERSE, LIQ)
    assert list(panel.columns) == PANEL_COLUMNS
    assert len(panel) == 12
    assert not panel.duplicated(subset=["ticker", "date"]).any()
    assert set(panel["bucket"]) == {"domestic_equity", "hy_credit"}


def test_panel_rolling_windows_do_not_cross_tickers():
    prices = {"AAA": _prices(seed=1), "BBB": _prices(seed=2)}
    panel = build_panel(prices, UNIVERSE, LIQ)
    # Within each ticker: first return is NaN and realized_vol needs 3 valid
    # returns, so rows 0-2 are NaN and row 3 is the first valid value.
    for _, grp in panel.groupby("ticker"):
        assert grp["ret"].isna().iloc[0]
        assert grp["realized_vol"].isna().iloc[:3].all()
        assert grp["realized_vol"].notna().iloc[3:].all()


def test_panel_liquidity_values_consistent():
    prices = {"AAA": _prices(seed=1)}
    panel = build_panel(prices, UNIVERSE.subset(["AAA"]), LIQ)
    row = panel.iloc[2]
    assert row["dollar_volume"] == pytest.approx(row["close"] * row["volume"])
    prev_close = panel.iloc[1]["close"]
    assert row["ret"] == pytest.approx(row["close"] / prev_close - 1)
    assert row["amihud"] == pytest.approx(
        abs(row["ret"]) / row["dollar_volume"] * 1e6
    )


def test_panel_unknown_ticker_raises():
    prices = {"ZZZ": _prices()}
    with pytest.raises(KeyError):
        build_panel(prices, UNIVERSE, LIQ)


def test_panel_empty_input_raises():
    with pytest.raises(ValueError):
        build_panel({}, UNIVERSE, LIQ)
