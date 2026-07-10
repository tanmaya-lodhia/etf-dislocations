"""Ingestion tests: parsing, caching, and error handling, all offline.
Network fetch functions are replaced with stubs returning canned CSV/JSON/
XLSX content - no live requests happen in this module.
"""

import io
import json

import pandas as pd
import pytest

from etf_dislocations.config import NavConfig, SpdrNavConfig, StooqConfig, YahooConfig
from etf_dislocations.data.ingest_nav import (
    fetch_spdr_navhist_xlsx,
    ingest_nav,
    load_nav_dir,
    parse_nav_csv,
    parse_spdr_navhist_xlsx,
)
from etf_dislocations.data.ingest_prices import (
    ingest_prices,
    ingest_prices_yahoo,
    parse_stooq_csv,
    parse_yahoo_chart_json,
)
from etf_dislocations.data.ingest_vix import (
    ingest_vix,
    ingest_vix_yahoo,
    load_vix_csv,
    parse_vix_csv,
)

STOOQ = StooqConfig(
    url_template="https://example.invalid/?s={symbol}",
    vix_symbol="^vix",
    price_symbols={"SPY": "spy.us"},
)
YAHOO = YahooConfig(
    url_template="https://example.invalid/chart/{symbol}",
    vix_symbol="^VIX",
    price_symbols={"SPY": "SPY"},
)
NAV_CFG = NavConfig(
    date_columns=("date", "Date", "As Of"),
    nav_columns=("nav", "NAV", "NAV per Share"),
)
SPDR_CFG = SpdrNavConfig(
    url_template="https://example.invalid/navhist-{symbol}.xlsx",
    tickers=frozenset({"SPY"}),
)

STOOQ_PRICES = (
    "Date,Open,High,Low,Close,Volume\n"
    "2024-01-02,100,101,99,100.5,1000\n"
    "2024-01-03,100.5,102,100,101.5,1200\n"
)
STOOQ_VIX = "Date,Open,High,Low,Close\n2024-01-02,13,15,12,14.5\n"

# Trimmed excerpt of the real anti-bot challenge page Stooq's endpoint began
# serving as of 2026-07-10 (see docs/live_data_audit.md) - the exact marker
# text this project's parser must recognize.
STOOQ_BOT_CHALLENGE_HTML = (
    '<!DOCTYPE html><html><head></head><body>'
    '<noscript>This site requires JavaScript to verify your browser. '
    "Please enable JavaScript and reload.</noscript>"
    "<script>(async()=>{...})()</script></body></html>"
)


def test_parse_stooq_csv():
    df = parse_stooq_csv(STOOQ_PRICES, "SPY")
    assert len(df) == 2
    assert df.loc["2024-01-03", "close"] == 101.5


def test_parse_stooq_rejects_non_csv():
    with pytest.raises(ValueError, match="not a Stooq CSV"):
        parse_stooq_csv("No data", "SPY")


def test_parse_stooq_detects_bot_challenge_distinctly():
    with pytest.raises(ValueError, match="anti-bot JS challenge"):
        parse_stooq_csv(STOOQ_BOT_CHALLENGE_HTML, "SPY")


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


# --- Yahoo chart JSON fallback (documented, opt-in; see live_data_audit.md) ---

def _yahoo_chart_json(dates, opens, highs, lows, closes, volumes):
    """Build a minimal chart-JSON payload matching Yahoo's real schema."""
    ts = [int(pd.Timestamp(d, tz="UTC").timestamp()) for d in dates]
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"timezone": "EDT"},
                        "timestamp": ts,
                        "indicators": {
                            "quote": [
                                {
                                    "open": opens,
                                    "high": highs,
                                    "low": lows,
                                    "close": closes,
                                    "volume": volumes,
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
    )


YAHOO_CHART_JSON = _yahoo_chart_json(
    ["2024-01-02T13:30:00", "2024-01-03T13:30:00"],
    [100.0, 100.5],
    [101.0, 102.0],
    [99.0, 100.0],
    [100.5, 101.5],
    [1000, 1200],
)


def test_parse_yahoo_chart_json():
    df = parse_yahoo_chart_json(YAHOO_CHART_JSON, "SPY")
    assert len(df) == 2
    assert df.loc["2024-01-03", "close"] == 101.5
    assert df.loc["2024-01-02", "volume"] == 1000


def test_parse_yahoo_chart_json_handles_null_bars():
    # Yahoo emits nulls for bars without a trade (e.g. some early-history
    # or thinly-traded days); clean_prices must drop these, not crash.
    text = _yahoo_chart_json(
        ["2024-01-02T13:30:00", "2024-01-03T13:30:00"],
        [100.0, None],
        [101.0, None],
        [99.0, None],
        [100.5, None],
        [1000, None],
    )
    df = parse_yahoo_chart_json(text, "SPY")
    assert len(df) == 1
    assert df.index[0] == pd.Timestamp("2024-01-02")


def test_parse_yahoo_chart_json_rejects_invalid_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_yahoo_chart_json("<html>not json</html>", "SPY")


def test_parse_yahoo_chart_json_surfaces_api_error():
    text = json.dumps(
        {"chart": {"result": None, "error": {"code": "Not Found"}}}
    )
    with pytest.raises(ValueError, match="Yahoo chart API error"):
        parse_yahoo_chart_json(text, "NOTREAL")


def test_ingest_prices_yahoo_caches_raw_and_writes_processed(tmp_path):
    urls = []

    def fake_fetch(url):
        urls.append(url)
        return YAHOO_CHART_JSON

    out = ingest_prices_yahoo(
        ["SPY"], YAHOO, tmp_path / "raw", tmp_path / "proc", fetch=fake_fetch
    )
    assert urls == ["https://example.invalid/chart/SPY"]
    assert len(out["SPY"]) == 2
    assert len(list((tmp_path / "raw" / "prices").glob("SPY_yahoo_*.csv"))) == 1
    written = pd.read_csv(tmp_path / "proc" / "prices" / "SPY.csv")
    assert len(written) == 2


def test_ingest_prices_yahoo_unmapped_ticker_raises(tmp_path):
    with pytest.raises(KeyError, match="ZZZ"):
        ingest_prices_yahoo(["ZZZ"], YAHOO, tmp_path, tmp_path, fetch=lambda u: "")


def test_ingest_vix_yahoo(tmp_path):
    out = ingest_vix_yahoo(
        YAHOO, tmp_path / "raw", tmp_path / "proc", fetch=lambda u: YAHOO_CHART_JSON
    )
    assert out.iloc[-1] == 101.5
    loaded = load_vix_csv(tmp_path / "proc" / "vix.csv")
    assert loaded.iloc[-1] == 101.5


# --- SPDR automated NAV history (documented fallback for SPDR-sponsored
# tickers only; see live_data_audit.md and data_sources.yaml) ---

def _spdr_navhist_xlsx(rows, footer=True):
    """Build a minimal workbook matching State Street's real navhist
    layout: 3-row header block, then Date/NAV/Shares/TotalAssets, then an
    optional disclaimer footer with blank/text rows."""
    header = [
        ["Fund Name:", "Test Fund", None, None],
        ["Ticker Symbol:", "SPY", None, None],
        [None, None, None, None],
        ["Date", "NAV", "Shares Outstanding", "Total Net Assets"],
    ]
    body = header + rows
    if footer:
        body += [[None, None, None, None], ["Before investing...", None, None, None]]
    df = pd.DataFrame(body)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="navhist", index=False, header=False)
    return buf.getvalue()


SPDR_XLSX = _spdr_navhist_xlsx(
    [
        ["09-Jul-2026", 751.69, 1041932116, 783212630071.01],
        ["08-Jul-2026", 745.60, 1045182116, 779287674044.72],
    ]
)


def test_parse_spdr_navhist_xlsx_happy_path():
    nav = parse_spdr_navhist_xlsx(SPDR_XLSX, "SPY")
    assert len(nav) == 2
    assert nav.loc["2026-07-09"] == pytest.approx(751.69)
    assert nav.index.is_monotonic_increasing


def test_parse_spdr_navhist_xlsx_drops_footer_and_bad_rows():
    xlsx = _spdr_navhist_xlsx(
        [
            ["09-Jul-2026", 751.69, 1041932116, 783212630071.01],
            ["08-Jul-2026", -1.0, 1045182116, 779287674044.72],  # bad NAV
        ],
        footer=True,
    )
    nav = parse_spdr_navhist_xlsx(xlsx, "SPY")
    assert len(nav) == 1  # negative NAV and footer text rows dropped


def test_parse_spdr_navhist_xlsx_missing_sheet_raises():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="wrong_sheet")
    with pytest.raises(ValueError, match="missing expected 'navhist' sheet"):
        parse_spdr_navhist_xlsx(buf.getvalue(), "SPY")


def test_ingest_nav_prefers_manual_csv_over_spdr(tmp_path):
    raw_nav = tmp_path / "nav"
    raw_nav.mkdir()
    pd.DataFrame({"date": ["2024-01-02"], "nav": [999.0]}).to_csv(
        raw_nav / "SPY.csv", index=False
    )
    calls = []
    out = ingest_nav(
        ["SPY"], raw_nav, tmp_path / "proc", NAV_CFG,
        spdr_cfg=SPDR_CFG,
        spdr_fetch=lambda url: calls.append(url) or SPDR_XLSX,
    )
    assert out["SPY"].iloc[0] == 999.0  # manual file wins
    assert calls == []  # SPDR fetch never called


def test_ingest_nav_falls_back_to_spdr_when_no_manual_file(tmp_path):
    raw_nav = tmp_path / "nav"
    raw_nav.mkdir()
    calls = []
    out = ingest_nav(
        ["SPY"], raw_nav, tmp_path / "proc", NAV_CFG,
        spdr_cfg=SPDR_CFG,
        spdr_fetch=lambda url: calls.append(url) or SPDR_XLSX,
    )
    assert calls == ["https://example.invalid/navhist-spy.xlsx"]
    assert len(out["SPY"]) == 2


def test_ingest_nav_non_spdr_ticker_without_manual_file_still_missing(tmp_path):
    raw_nav = tmp_path / "nav"
    raw_nav.mkdir()
    out = ingest_nav(
        ["LQD"], raw_nav, tmp_path / "proc", NAV_CFG, spdr_cfg=SPDR_CFG,
    )
    assert out == {}
