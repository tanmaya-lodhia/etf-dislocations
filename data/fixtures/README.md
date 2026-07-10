# Fixture data — SYNTHETIC, NOT REAL

Everything in this directory is **synthetic**, generated deterministically by
`scripts/make_fixtures.py` (seed 20260710). It exists so the pipeline and test
suite run fully offline on a fresh clone.

- `prices/<TICKER>.csv` — daily OHLCV for 5 universe tickers (SPY, EFA, LQD,
  HYG, TLT), 260 business days from 2024-01-02. Trading days 60–80 have
  3x volatility and 2.5x volume to simulate a stress window.
- Ticker symbols are reused from the real universe purely so the fixture flows
  through the same config; the numbers bear no relation to real market data.

**Never present fixture-mode output as an empirical result** (SPEC.md
section 5.4). Fixture-mode panel output is written with a `_fixture` suffix to
keep it distinguishable.
