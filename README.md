# When the Wrapper Cracks: ETF Dislocations, Arbitrage Frictions, and Liquidity Stress

Research pipeline studying whether ETF premium/discount dislocations during
market stress are driven by ETF trading pressure, underlying-market
illiquidity, or arbitrage frictions. See [SPEC.md](SPEC.md) for the full
design; this README will be expanded as milestones land (SPEC.md section 9).

## Status

Milestone 1 complete: package skeleton, config system, offline fixture
dataset, fixture loading, panel construction, and basic liquidity metrics
(dollar volume, daily returns, realised volatility, Amihud illiquidity).

## Quickstart

```bash
pip install -e ".[dev]"
pytest                                      # full suite, runs offline
etf-dislocations build-panel --mode fixture # writes data/panel/etf_day_panel_fixture.csv
```

Fixture data is synthetic (see `data/fixtures/README.md`) — fixture-mode
output is never an empirical result.
