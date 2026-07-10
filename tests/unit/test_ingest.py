"""Ingestion tests: parsing, caching, and error handling, all offline.
Network fetch functions are replaced with stubs returning canned CSV text.
"""

import pandas as pd
import pytest

from etf_dislocations.config import NavConfig, StooqConfig
from etf_dislocations.data.ingest_nav import ingest_nav, load_nav_dir, parse_nav_csv
from etf_dislocations.data.ingest_prices import ingest_prices, parse_stooq_csv
from etf_dislocations.data.ingest_vix import ingest_vix, load_vix_csv, parse_vix_csv

STOOQ = StooqConfig(
    url_template="https://example.invalid/?s={symbol}",
    vix_symbol="^vix",
    price_symbols={"SPY": "spy.us"},
)
NAV_CFG = NavConfig(
    date_columns=("date", "Date", "As Of"),
    nav_columns=("nav", "NAV", "NAV per Share"),
)

STOOQ_PRICES = (
    "Date,Open,High,Low,Close,Volume\n"
    "2024-01-02,100,101,99,100.5,1000\n"
    "2024-01-03,100.5,102,100,101.5,1200\n"
)
STOOQ_VIX = "Date,Open,High,Low,Close\n2024-01-02,13,15,12,14.5\n"


def test_parse_stooq_csv():
    df = parse_stooq_csv(STOOQ_PRICES, "SPY")
    assert len(df) == 2
    assert df.loc["2024-01-03", "close"] == 101.5


def test_parse_stooq_rejects_non_csv():
    with pytest.raises(ValueError, match="not a Stooq CSV"):
        parse_stooq_csv("No data", "SPY")


def test_ingest_prices_caches_raw_and_writes_processed(tmp_path):
    urls = []

    def fake_fetch(url):
        urls.append(url)
        return STOOQ_PRICES

    out = ingest_prices(
        ["SPY"], STOOQ, tmp_path / "raw", tmp_path / "proc", fetch=fake_fetch
    )
    assert urls == ["https://example.invalid/?s=spy.us"]
    assert len(out["SPY"]) == 2
    assert len(list((tmp_path / "raw" / "prices").glob("SPY_*.csv"))) == 1
    written = pd.read_csv(tmp_path / "proc" / "prices" / "SPY.csv")
    assert len(written) == 2


def test_ingest_prices_unmapped_ticker_raises(tmp_path):
    with pytest.raises(KeyError, match="ZZZ"):
        ingest_prices(["ZZZ"], STOOQ, tmp_path, tmp_path, fetch=lambda u: "")


def test_parse_and_ingest_vix(tmp_path):
    vix = parse_vix_csv(STOOQ_VIX)
    assert vix.iloc[0] == 14.5

    out = ingest_vix(STOOQ, tmp_path / "raw", tmp_path / "proc",
                     fetch=lambda u: STOOQ_VIX)
    assert out.iloc[0] == 14.5
    loaded = load_vix_csv(tmp_path / "proc" / "vix.csv")
    assert loaded.iloc[0] == 14.5


def test_parse_nav_csv_sponsor_headers():
    raw = pd.DataFrame(
        {"As Of": ["2024-01-02", "2024-01-03"], "NAV per Share": [100.1, -1.0]}
    )
    nav = parse_nav_csv(raw, "LQD", NAV_CFG)
    assert len(nav) == 1  # negative NAV dropped
    assert nav.iloc[0] == 100.1


def test_parse_nav_csv_unknown_headers_raise():
    raw = pd.DataFrame({"when": ["2024-01-02"], "value": [100.0]})
    with pytest.raises(ValueError, match="date/NAV columns"):
        parse_nav_csv(raw, "LQD", NAV_CFG)


def test_ingest_nav_skips_missing_files_with_warning(tmp_path):
    raw_nav = tmp_path / "nav"
    raw_nav.mkdir()
    pd.DataFrame({"date": ["2024-01-02"], "nav": [100.0]}).to_csv(
        raw_nav / "SPY.csv", index=False
    )
    out = ingest_nav(["SPY", "LQD"], raw_nav, tmp_path / "proc", NAV_CFG)
    assert set(out) == {"SPY"}
    with pytest.raises(FileNotFoundError):
        ingest_nav(["LQD"], raw_nav, tmp_path / "proc", NAV_CFG, require_all=True)


def test_load_nav_dir_roundtrip(tmp_path):
    nav_dir = tmp_path / "nav"
    nav_dir.mkdir()
    pd.DataFrame(
        {"date": ["2024-01-02", "2024-01-03"], "nav": [100.0, 100.5]}
    ).to_csv(nav_dir / "SPY.csv", index=False)
    out = load_nav_dir(nav_dir)
    assert list(out) == ["SPY"]
    assert out["SPY"].iloc[1] == 100.5
    with pytest.raises(FileNotFoundError, match="LQD"):
        load_nav_dir(nav_dir, ["SPY", "LQD"])
