# When the Wrapper Cracks: ETF Dislocations, Arbitrage Frictions, and Liquidity Stress

Research pipeline studying whether ETF premium/discount dislocations during
market stress are driven by ETF trading pressure, underlying-market
illiquidity, or arbitrage frictions. See [SPEC.md](SPEC.md) for the full
design; this README will be expanded as milestones land (SPEC.md section 9).

## Status

Milestones 1-5 complete: package skeleton, config system, offline fixture
dataset, public-mode ingestion (Stooq prices/VIX, manually downloaded sponsor
NAV files), premium/discount computation, the liquidity measure set
(dollar volume, returns, realised volatility, Amihud, Corwin-Schultz and
high-low spread proxies, abnormal volume, international stale-pricing flag),
stress-window classification (pre-registered Tier-1 event windows plus the
rule-based Tier-2 VIX/premium-volatility flags), the dislocation event
study (calm-baseline abnormal premium/discount, confidence bands,
time-to-normalization, bucket-level summaries and figures), the panel
regression (pre-registered channel specifications, entity/time fixed
effects, two-way clustered standard errors), the mean-reversion
analysis (per-ETF AR(1) half-lives by calm/stress regime with an
interaction test for the persistence shift), and the robustness suite
(placebo event windows, alternative dislocation/spread measures, Tier-2
threshold sensitivity, event exclusion, winsorisation).

## Quickstart

```bash
pip install -e ".[dev]"
pytest                                # full suite, runs offline
etf-dislocations run-all --mode fixture
```

The fixture run needs no data setup and writes the complete output set
(panel, event study, regressions, mean reversion, robustness, manifest) to
`reports/fixture_run/`. Individual stages are also available as subcommands
(`build-panel`, `event-study`, `panel-regression`, `mean-reversion`,
`robustness`).

For real data: place sponsor NAV downloads in `data/raw/nav/<TICKER>.csv`
(see `docs/data_notes.md`), then

```bash
etf-dislocations ingest --mode public
etf-dislocations run-all --mode public
```

## Reproducibility

Fixture mode runs fully offline from checked-in synthetic data. Every run
writes `run_manifest.json` with a SHA-256 per output file; repeated runs on
the same inputs are byte-identical (enforced by an integration test).

Fixture data is synthetic (see `data/fixtures/README.md`) — fixture-mode
output is never an empirical result.
