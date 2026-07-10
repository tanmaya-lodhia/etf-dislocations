# SPEC.md — When the Wrapper Cracks: ETF Dislocations, Arbitrage Frictions, and Liquidity Stress

Master specification for this repository. Every future coding session should read this file
instead of re-deriving the design. If an implementation decision is not covered here, add it
here first, then implement it.

---

## 0. One-paragraph summary

ETFs promise continuous, arbitrage-enforced pricing: the market price should track NAV because
authorized participants (APs) can create/redeem shares to close any gap. In stress, that
mechanism can jam — underlying securities stop trading, APs step back, and the "wrapper"
(the ETF's market price) can trade meaningfully away from the value of what it holds. This
project builds a reproducible research pipeline to measure ETF premium/discount dislocations
around known stress events, decompose whether the dislocation is better explained by
ETF-side trading pressure, underlying-market illiquidity, or arbitrage-mechanism frictions, and
test whether dislocations mean-revert at a rate consistent with a functioning creation/redemption
mechanism. It is a market-structure study, not a returns or portfolio-construction study.

---

## 1. Project objectives

### 1.1 Research motivation

ETF assets under management have grown to a scale where the wrapper itself is systemically
relevant. Regulators (SEC, FSB, IOSCO) and practitioners have repeatedly flagged episodes where
ETF prices decoupled from NAV: the March 2020 COVID liquidity crisis (notably in fixed-income
ETFs such as LQD and HYG, where discounts exceeded 3–5%), flash-crash events (24 August 2015),
and periodic single-day dislocations in sector and international-equity ETFs when underlying
markets are closed or illiquid (e.g., international-equity ETFs trading against stale foreign
closing prices). Asset managers that sponsor ETFs (BlackRock/iShares being the largest) have a
direct commercial and fiduciary interest in understanding *why* these dislocations happen,
*how big* they get, and *how fast* they resolve, because it affects investor trust, AP economics,
and product design (creation basket composition, cash vs. in-kind creation, listing multiple
tranches, etc.).

This project treats the ETF premium/discount as a measurable signal of market-structure stress
and asks what drives it, using only public data and fully reproducible methods.

### 1.2 Research question

**During market stress, are ETF premium/discount dislocations primarily driven by (a) ETF
trading pressure, (b) underlying-market illiquidity, or (c) arbitrage frictions in the
creation/redemption mechanism?**

Sub-questions:

- How does the magnitude and persistence of premium/discount dislocation vary across asset
  classes (equity, fixed income, international) and across known stress windows?
- Does dislocation mean-revert at a rate consistent with an intact arbitrage mechanism, and
  does that rate degrade during stress?
- Which observable frictions (bid-ask spreads, underlying market hours mismatch, bond-market
  illiquidity proxies, ETF volume/turnover spikes) best explain cross-sectional and time-series
  variation in dislocation?

### 1.3 Hypotheses

- **H1 (Illiquidity transmission):** Dislocation magnitude increases with underlying-market
  illiquidity (proxied by bond-ETF vs. equity-ETF comparisons, bid-ask spreads on underlying
  proxies, and stale-pricing indicators for international ETFs), independent of ETF-side volume.
- **H2 (ETF trading-pressure channel):** Abnormal ETF share volume/turnover around stress events
  is associated with larger same-day dislocation, controlling for underlying illiquidity —
  consistent with a demand/supply imbalance that the AP mechanism has not yet absorbed.
- **H3 (Arbitrage-friction channel):** The half-life of dislocation (mean-reversion speed)
  lengthens during stress windows relative to calm windows, and this effect is stronger for
  ETFs whose underlying baskets are structurally harder to arbitrage (fixed income, international
  equity) than for liquid domestic-equity ETFs.
- **H4 (Cross-sectional ranking):** Fixed-income ETFs exhibit larger and more persistent
  dislocations than domestic-equity ETFs during the same stress window, consistent with
  underlying bond-market illiquidity being a first-order driver rather than ETF-specific
  trading pressure alone.

The project does not need all hypotheses to be confirmed — a central deliverable is an honest,
evidence-based verdict on which channel dominates, including null or mixed results.

### 1.4 Expected contribution

- A reproducible, extensible pipeline for measuring ETF premium/discount from public data only,
  usable for any listed ETF with a public iNAV/NAV history.
- A panel-regression decomposition of dislocation drivers that separates ETF-side, underlying-side,
  and mechanism-side explanatory variables — most public commentary on this topic is qualitative
  (regulatory reports, sponsor whitepapers) rather than a quantitative, event-study-based decomposition
  built from first principles.
- An event-study library of known stress windows with quantified before/during/after dislocation
  and mean-reversion statistics, directly relevant to how an ETF issuer would monitor and explain
  wrapper behavior in stress.
- A demonstration of research and engineering practice suitable for a BlackRock/iShares
  quantitative research, portfolio management, or risk application: clean data lineage, explicit
  assumptions, reproducibility, and honest limitations rather than overstated conclusions.

### 1.5 Scope

In scope:

- U.S.-listed ETFs across equity (domestic and international) and fixed income.
- Daily-frequency and, where available, intraday-frequency analysis of premium/discount.
- Public data sources only (see §2, §5).
- Event studies around a fixed, pre-registered list of known stress windows.
- Panel regression and mean-reversion (AR(1)/half-life) analysis of dislocation.
- A "public-proxy mode" that runs end-to-end on freely available data, and an optional
  "NAV-enhanced mode" that upgrades fidelity if higher-quality NAV/iNAV data becomes available.

Out of scope (see also §10 Future Extensions):

- Live trading, execution, or portfolio construction.
- Proprietary AP-level flow data, exchange order-book microstructure data, or paid vendor NAV
  feeds (Bloomberg, Refinitiv) — the project must run without them.
- Non-U.S.-listed ETFs (data availability constraint).
- Options, leveraged/inverse ETFs, and actively managed non-transparent ETFs (structurally
  different arbitrage mechanics; explicitly excluded to keep the mechanism comparable across
  the universe).

### 1.6 Limitations (to be stated honestly in the paper, not hidden)

- **NAV data quality:** Free sources provide *end-of-day* NAV, not real-time iNAV (intraday
  indicative NAV, disseminated every 15 seconds by exchanges). Intraday premium/discount
  dynamics therefore cannot be measured with full fidelity in public-proxy mode; the project
  measures *daily-close* premium/discount as the primary signal and treats intraday analysis as
  a stretch goal gated on data availability (NAV-enhanced mode).
- **No AP-level data:** Creation/redemption unit flows are not public in real time. Arbitrage
  friction is proxied indirectly (via mean-reversion speed and underlying-liquidity proxies),
  not observed directly. This is disclosed as a proxy, not a measurement, throughout.
- **Small stress-event sample:** There are only a handful of clearly identifiable, severe
  market-wide stress windows in the data-available era (2015 flash crash, Dec 2018 selloff,
  March 2020 COVID crash, 2022 rates selloff, occasional single-day events). Statistical power
  for the event study is inherently limited; this is addressed by supplementing rare severe
  events with a larger sample of milder, more frequent stress days (defined via a volatility/
  liquidity threshold rule, §2.7) so the panel regression has adequate sample size, while the
  headline event studies focus on the small set of canonical severe episodes.
- **Survivorship/selection:** The ETF universe is chosen from currently-listed, long-running
  funds; funds that closed or merged during a stress period are not included, which could bias
  results toward "ETFs that survived stress."
- **Free-data structural gaps:** No paid terminal, no proprietary spread/liquidity data. All
  liquidity proxies are constructed from public quote/trade data with explicitly stated
  assumptions.

---

## 2. Research methodology

### 2.1 ETF universe

A fixed, pre-registered universe (not survivorship-mined after seeing results), chosen to span
the structural dimensions the hypotheses require:

| Bucket | Tickers | Role |
|---|---|---|
| Domestic equity (liquid, easy arbitrage) | SPY, IVV, QQQ | Baseline / "easy" arbitrage control |
| Domestic equity (sector, medium liquidity) | XLF, XLE, XLK | Medium-liquidity equity comparison |
| International equity (time-zone mismatch) | EFA, EEM, VWO | Stale-pricing / arbitrage-friction test |
| Investment-grade fixed income | LQD, AGG, BND | Underlying-illiquidity test (IG credit) |
| High-yield fixed income | HYG, JNK | Underlying-illiquidity test (HY credit, hardest to arbitrage) |
| Treasury / rates | TLT, IEF, SHY | Rates-liquidity control, usually easier to arbitrage than credit |

~17 tickers. Deliberately excludes leveraged/inverse and non-transparent active ETFs (different
arbitrage mechanics, would confound the cross-sectional comparison). The universe list is a
config file (`config/universe.yaml`), not hardcoded, so it can be extended without code changes.

### 2.2 Required datasets (must have for MVP)

- **ETF daily OHLCV (market price):** e.g., via `yfinance` / Stooq / Nasdaq Data Link free tier.
  Public, no key required for basic daily bars.
- **ETF daily NAV:** Sponsor websites (iShares, State Street/SPDR, Vanguard fund pages, or
  `stockanalysis.com` / fund-specific historical NAV CSV downloads) publish daily NAV history for
  free. This is the single most important input and is treated as the critical data-availability
  risk (see §5.4, Milestone 1 risk log).
- **Underlying benchmark index level (daily close):** where free proxies exist (e.g., S&P 500
  index level for SPY/IVV) to sanity-check NAV against a fair-value proxy.
- **Trading calendar data:** market holiday/half-day calendars for both U.S. and relevant
  foreign markets (for the international-equity stale-pricing tests), via `pandas_market_calendars`.

### 2.3 Optional datasets (nice-to-have, gated by availability)

- **Intraday iNAV / intraday ETF quotes:** if a free source becomes available (some data
  vendors offer limited historical intraday snapshots); unlocks NAV-enhanced mode.
- **TRACE bond-level trade data (FINRA, public, but bulky):** for a direct underlying
  fixed-income liquidity proxy (trade counts, size, dealer spreads) rather than an indirect proxy.
- **Fed / Treasury market liquidity indices** (e.g., Bloomberg/Fed-published liquidity stress
  indices, if a free public series exists) as an independent stress-window validation signal.
- **Options-implied bid-ask / market-maker inventory proxies** — explicitly out of scope for MVP,
  flagged as a future extension only if it does not compromise the "public data, no scraping"
  constraint.

### 2.4 Public-proxy mode (default, must always work)

The pipeline's default and required operating mode. Uses only: free daily OHLCV, free daily
NAV from sponsor/aggregator downloads, and free calendar data. All headline results (paper,
memo) are produced in this mode. This is the mode that must run end-to-end from checked-in
fixtures with zero network access (see §5).

### 2.5 NAV-enhanced mode (optional upgrade path)

If higher-frequency or higher-quality NAV data is obtained (e.g., intraday iNAV snapshots),
the same pipeline modules should accept it as a drop-in replacement for the daily-NAV data
source, producing a finer-grained intraday premium/discount series and enabling true intraday
event-study windows. This is a data-layer swap, not a methodology change: the interfaces
(§3, §5) must be designed so that NAV-enhanced mode requires no changes to the analysis modules,
only to the data-ingestion layer and a config flag.

### 2.6 Liquidity measures

Underlying-market illiquidity proxies (public-data constructible):

- **Amihud illiquidity ratio** on the ETF's benchmark index / representative bond index proxy:
  `|return| / dollar_volume`, averaged over a rolling window.
- **Quoted/effective bid-ask spread proxy** on the ETF itself, via High-Low or Corwin-Schultz
  (2012) high-low spread estimator (constructible from daily OHLC only, no tick data needed —
  chosen specifically because it works with free daily data).
- **ETF turnover** (daily dollar volume / AUM proxy, or / shares outstanding if obtainable) as a
  demand-pressure proxy (used for the ETF trading-pressure channel, H2).
- **Premium/discount volatility** (rolling std. dev. of daily premium/discount) as a stress
  indicator in its own right.
- **Stale-pricing flag** for international-equity ETFs: an indicator for days where the foreign
  underlying market was closed or closed >X hours before the U.S. close, used to isolate the
  time-zone-mismatch component of dislocation from genuine illiquidity.

### 2.7 Stress windows

A pre-registered list of stress windows, defined *before* running the analysis, split into two
tiers:

**Tier 1 — canonical severe events (small n, headline event studies):**
- 24 August 2015 flash crash (~1 week window)
- December 2018 equity selloff (~2 week window)
- March 2020 COVID crash (~4–6 week window, the primary/headline event)
- September–October 2022 UK gilt crisis / global rates selloff (~2 week window)

**Tier 2 — rule-based stress days (larger n, feeds the panel regression):**
A day is flagged "stress" if VIX level or VIX daily change exceeds a pre-specified percentile
threshold (e.g., top 5% of the sample period) OR the ETF's own premium/discount volatility
exceeds a rolling threshold. Thresholds and lookback windows are fixed in config
(`config/stress_rules.yaml`) before estimation, not tuned post hoc.

### 2.8 Event-study methodology

For each Tier-1 stress window and each ETF:

- Define event window (e.g., [-10, +20] trading days around window start) and a calm-period
  estimation window (e.g., prior 120 trading days) for baseline premium/discount and its
  volatility.
- Compute abnormal dislocation = observed premium/discount minus the calm-period baseline mean,
  with confidence bands from the calm-period distribution.
- Report cross-sectional average abnormal dislocation by asset-class bucket (equity vs.
  international vs. IG credit vs. HY credit vs. rates), with standard errors clustered by event
  window.
- Report time-to-normalization: number of trading days until abnormal dislocation returns within
  the calm-period confidence band.

### 2.9 Panel regression design

Panel of ETF-day observations (ETF × trading day), pooled across Tier-2 stress days and matched
calm days.

Dependent variable: `abs(premium_discount)` (or signed, as a robustness alternative) at day *t*.

Candidate explanatory variables, grouped by hypothesized channel:

- **ETF-pressure channel:** ETF turnover z-score, ETF volume abnormal (vs. own 60-day average),
  ETF bid-ask spread proxy.
- **Underlying-illiquidity channel:** Amihud illiquidity ratio on underlying proxy, asset-class
  dummy (equity/international/IG/HY/rates), interaction of asset-class dummy with stress-day
  indicator.
- **Arbitrage-friction channel:** stale-pricing flag (international), lagged premium/discount
  (for mean-reversion controls — see §2.10), a fixed-income dummy interacted with stress-day
  indicator (proxy for basket-level arbitrage difficulty).
- **Controls:** day-of-week, ETF fixed effects, stress-window fixed effects, VIX level.

Estimation: pooled OLS with clustered standard errors (by ETF and by date, two-way clustering)
as the baseline; ETF and time fixed effects as a robustness specification. All specifications
and variable definitions fixed in a config/spec file before running, to avoid specification
search being mistaken for a result.

### 2.10 Mean-reversion analysis

For each ETF, estimate an AR(1) model of daily premium/discount:
`pd_t = alpha + beta * pd_{t-1} + epsilon_t`,
separately for calm-period and stress-period subsamples, and report the implied half-life
`ln(0.5)/ln(beta)`. Compare half-lives:

- across asset-class buckets (H3, H4),
- between calm and stress subsamples for the same ETF (H3),
- with a formal test (e.g., Chow-type break test or bootstrap comparison of beta across regimes)
  for whether the calm-vs-stress difference in beta is statistically distinguishable from noise.

### 2.11 Robustness checks

- Alternative dislocation measure: log(price/NAV) vs. simple (price − NAV)/NAV.
- Alternative stress-day thresholds (sensitivity to the Tier-2 percentile cutoff).
- Exclusion of March 2020 alone (to check results aren't purely a single-event artifact).
- Placebo test: repeat the event study on randomly chosen non-stress windows of the same length,
  confirm abnormal dislocation is statistically indistinguishable from zero.
- Alternative spread proxy (Corwin-Schultz vs. simple High-Low range) for the liquidity channel.
- Winsorization/outlier sensitivity for the panel regression.
- Out-of-sample check: hold out one Tier-1 event (e.g., 2022 rates selloff) from panel
  estimation, confirm the fitted relationship still describes that event reasonably.

---

## 3. Repository architecture

Architecture only — no code, no placeholder implementations.

```
etf-dislocations/
├── SPEC.md                        # this file — master spec, read first
├── README.md                      # public-facing project overview (see §9)
├── pyproject.toml                 # Python 3.11/3.12, dependency pinning
├── config/
│   ├── universe.yaml               # ETF ticker list + asset-class bucket tags
│   ├── stress_windows.yaml         # Tier-1 event window definitions
│   ├── stress_rules.yaml           # Tier-2 rule thresholds (percentiles, lookbacks)
│   ├── data_sources.yaml           # source URLs/providers per dataset, mode flags
│   └── regression_spec.yaml        # fixed panel regression variable list/specifications
├── data/
│   ├── raw/                        # untouched downloads, one subfolder per source
│   ├── processed/                  # cleaned, aligned, ticker-level daily series
│   ├── panel/                      # final ETF-day panel used for regression/event study
│   └── fixtures/                   # small, checked-in synthetic/sample data for offline mode
├── src/
│   └── etf_dislocations/
│       ├── __init__.py
│       ├── data/
│       │   ├── ingest_prices.py        # ETF OHLCV download/load
│       │   ├── ingest_nav.py           # NAV download/load (sponsor + aggregator sources)
│       │   ├── ingest_calendars.py     # trading calendar / market-hours data
│       │   ├── ingest_vix.py           # VIX level series for stress-day rule
│       │   └── align.py                # date alignment, missing-data handling, mode switch
│       ├── liquidity/
│       │   ├── amihud.py               # Amihud illiquidity ratio
│       │   ├── spread_estimators.py    # Corwin-Schultz / High-Low spread proxies
│       │   └── turnover.py             # ETF turnover / abnormal volume
│       ├── dislocation/
│       │   ├── premium_discount.py     # core premium/discount computation
│       │   └── stale_pricing.py        # international stale-pricing flag
│       ├── stress/
│       │   ├── tier1_events.py         # canonical event window lookup
│       │   └── tier2_rule.py           # rule-based stress-day flagging
│       ├── analysis/
│       │   ├── event_study.py          # abnormal dislocation, time-to-normalization
│       │   ├── panel_regression.py     # pooled OLS, fixed effects, clustered SE
│       │   ├── mean_reversion.py       # AR(1) / half-life estimation, regime comparison
│       │   └── robustness.py           # placebo tests, alternative specs, sensitivity
│       └── reporting/
│           ├── tables.py               # formatted regression/event-study tables
│           └── figures.py              # standard plot set (see below)
├── scripts/
│   ├── run_ingest.py                # orchestrates data/ ingestion end-to-end
│   ├── build_panel.py                # builds data/panel/ from data/processed/
│   ├── run_event_study.py            # produces event-study outputs
│   ├── run_panel_regression.py       # produces regression outputs
│   ├── run_mean_reversion.py         # produces mean-reversion outputs
│   └── run_all.py                    # full pipeline, fixture-mode by default
├── notebooks/
│   └── exploratory/                  # scratch analysis only, never a dependency of scripts/
├── reports/
│   ├── paper/                        # LaTeX or Markdown source for the academic paper
│   ├── memo/                         # executive memo source
│   └── figures/                      # generated output figures (gitignored except samples)
├── tests/
│   ├── unit/                         # one test module per src/ module
│   ├── integration/                  # full-pipeline-on-fixtures tests
│   └── data/                         # tiny synthetic CSVs used only by tests
└── docs/
    └── data_notes.md                 # per-source caveats, access dates, licensing notes
```

Design principles:

- `src/etf_dislocations/` is a proper installable package; `scripts/` are thin CLI entry points
  that call into it — no analysis logic lives in `scripts/` or `notebooks/`.
- Every module under `analysis/` takes the panel (or processed series) as an explicit input and
  returns a typed result object/dataframe — no hidden global state, no reading files mid-analysis.
- Mode switching (public-proxy vs. NAV-enhanced) is a config flag consumed by `data/align.py`,
  not a branch scattered across analysis modules.
- `data/fixtures/` + `tests/integration/` together guarantee `scripts/run_all.py` produces output
  with zero network access, using synthetic/sample data explicitly labeled as such.

---

## 4. Milestones

Each milestone is independently implementable and independently testable. Order reflects
dependency, but a coding session can pick up any milestone if its predecessors' outputs already
exist (real or fixture).

### Milestone 0 — Repository scaffolding
- **Objective:** Stand up the package skeleton, config files, and empty test scaffolding so every
  later milestone has a place to land.
- **Files:** `pyproject.toml`, `config/*.yaml` (with placeholder-but-valid content, i.e. the real
  universe/stress-window lists, not TODO stubs), `src/etf_dislocations/__init__.py`, empty module
  files per §3 tree, `tests/` directories.
- **Tests:** a single smoke test that the package imports and config files parse.
- **Expected outputs:** installable package (`pip install -e .`), valid parsed config objects.
- **Completion criteria:** `pip install -e .` succeeds; config YAML files load without error and
  match the schema described in §2.1/§2.7.

### Milestone 1 — Data ingestion (public-proxy mode)
- **Objective:** Ingest ETF OHLCV, ETF NAV, VIX, and trading-calendar data for the full universe,
  saved to `data/raw/` and `data/processed/`, with an offline-fixture fallback.
- **Files:** `src/etf_dislocations/data/ingest_prices.py`, `ingest_nav.py`, `ingest_calendars.py`,
  `ingest_vix.py`, `align.py`, `scripts/run_ingest.py`, `data/fixtures/*`.
- **Tests:** unit tests for each ingestion function against fixture inputs; integration test that
  `run_ingest.py --mode fixture` produces a complete `data/processed/` set with no network calls.
- **Expected outputs:** per-ticker daily price and NAV CSVs in `data/processed/`, a calendar
  lookup table, a VIX series.
- **Completion criteria:** fixture-mode ingestion runs end-to-end offline; a documented (in
  `docs/data_notes.md`) manual verification that at least the NAV source works for a small sample
  of real tickers. **Risk flag:** free daily-NAV availability/format per sponsor is the single
  biggest risk in the project; this milestone must resolve or explicitly document the fallback
  (e.g., NAV proxy via published closing NAV files vs. computed from constituent data) before
  later milestones depend on it.

### Milestone 2 — Premium/discount and liquidity measures
- **Objective:** Compute the core premium/discount series and all liquidity proxies from
  processed data.
- **Files:** `dislocation/premium_discount.py`, `dislocation/stale_pricing.py`,
  `liquidity/amihud.py`, `liquidity/spread_estimators.py`, `liquidity/turnover.py`.
- **Tests:** unit tests with hand-computed expected values on small synthetic series (e.g., a
  3-row DataFrame where premium/discount and Amihud ratio can be verified by hand).
- **Expected outputs:** `data/processed/<ticker>_dislocation.csv` with premium/discount,
  liquidity proxies, and stale-pricing flag columns.
- **Completion criteria:** numerical outputs match hand-calculated fixture expectations exactly
  (within floating-point tolerance); spread estimator matches the published Corwin-Schultz
  formula on a textbook example.

### Milestone 3 — Stress-window construction
- **Objective:** Implement Tier-1 event-window lookup and Tier-2 rule-based stress-day flagging.
- **Files:** `stress/tier1_events.py`, `stress/tier2_rule.py`, `config/stress_windows.yaml`,
  `config/stress_rules.yaml`.
- **Tests:** unit tests that known dates (e.g., 2020-03-16) are correctly flagged as Tier-1;
  unit tests on synthetic VIX series that the Tier-2 percentile rule flags the expected days.
- **Expected outputs:** a stress-day flag column joined onto the panel per ETF-day.
- **Completion criteria:** Tier-1 windows match the pre-registered list in §2.7 exactly; Tier-2
  rule is deterministic and reproducible from config alone.

### Milestone 4 — Panel construction
- **Objective:** Assemble the final ETF-day panel joining price, NAV, dislocation, liquidity,
  and stress flags across the whole universe and sample period.
- **Files:** `scripts/build_panel.py`, panel schema documented in `docs/data_notes.md`.
- **Tests:** integration test that `build_panel.py` on fixtures produces a panel with the
  expected shape, no unexpected nulls in required columns, and correct ETF/date uniqueness.
- **Expected outputs:** `data/panel/etf_day_panel.parquet` (or csv).
- **Completion criteria:** panel passes a schema-validation test (column presence, types,
  no duplicate ETF-day keys) on both fixture and (if available) real data.

### Milestone 5 — Event-study analysis
- **Objective:** Implement abnormal-dislocation and time-to-normalization event-study
  calculations for Tier-1 windows.
- **Files:** `analysis/event_study.py`, `scripts/run_event_study.py`, `reporting/tables.py`
  (event-study table), `reporting/figures.py` (event-window plot).
- **Tests:** unit tests on synthetic pre/post series with known abnormal-dislocation values;
  test that confidence-band computation matches a manual calculation.
- **Expected outputs:** per-event, per-ETF abnormal dislocation table; cross-sectional
  asset-class summary table; event-window plots.
- **Completion criteria:** reproduces identical numeric output on fixture data across repeated
  runs (determinism test); table/figure generation runs without manual intervention.

### Milestone 6 — Panel regression analysis
- **Objective:** Implement the fixed panel regression specification (pooled OLS + FE variants,
  clustered SE) exactly as defined in `config/regression_spec.yaml`.
- **Files:** `analysis/panel_regression.py`, `scripts/run_panel_regression.py`.
- **Tests:** unit test against a known textbook/synthetic dataset with a known OLS coefficient
  (e.g., regression on data with an exactly-constructed linear relationship plus small noise,
  checking recovered coefficients within tolerance); test that clustering changes standard
  errors as expected relative to non-clustered baseline.
- **Expected outputs:** regression coefficient table(s) with all specifications from
  `regression_spec.yaml`, saved to `reports/`.
- **Completion criteria:** regression runs end-to-end on the Milestone 4 panel; coefficients and
  SEs are reproducible bit-for-bit given the same panel and config (no unseeded randomness).

### Milestone 7 — Mean-reversion analysis
- **Objective:** Implement AR(1)/half-life estimation per ETF and per regime (calm vs. stress),
  plus the regime-comparison test.
- **Files:** `analysis/mean_reversion.py`, `scripts/run_mean_reversion.py`.
- **Tests:** unit test AR(1) fit and half-life formula against a synthetic series with known
  true beta; test regime-comparison logic on synthetic calm/stress subsamples with a known
  difference in persistence.
- **Expected outputs:** per-ETF half-life table (calm vs. stress), regime-break test results.
- **Completion criteria:** half-life values match hand-calculated values on synthetic AR(1) data
  within numerical tolerance.

### Milestone 8 — Robustness suite
- **Objective:** Implement the robustness checks in §2.11 as a runnable, documented suite rather
  than ad hoc scripts.
- **Files:** `analysis/robustness.py`, integrated calls from `scripts/run_all.py --robustness`.
- **Tests:** unit tests per robustness check confirming each runs and returns a well-formed
  result object; placebo test unit-tested to confirm it correctly identifies "no effect" on
  genuinely random synthetic windows.
- **Expected outputs:** robustness results table appended to `reports/`.
- **Completion criteria:** all robustness checks listed in §2.11 are runnable from a single
  command and produce results consumable by the reporting layer.

### Milestone 9 — Reporting layer
- **Objective:** Turn analysis outputs into publication-ready tables/figures used by the paper
  and memo, without embedding analysis logic in the reporting code.
- **Files:** `reporting/tables.py`, `reporting/figures.py`.
- **Tests:** unit tests that table/figure functions accept the documented result-object schema
  and produce non-empty, correctly-labeled output (e.g., correct column headers, correct number
  of rows) on synthetic inputs.
- **Expected outputs:** a fixed set of standard figures (premium/discount time series with
  stress windows shaded; cross-sectional dislocation-by-bucket bar chart; half-life
  calm-vs-stress comparison chart; regression coefficient plot) and tables in `reports/figures/`
  and `reports/paper/tables/`.
- **Completion criteria:** `scripts/run_all.py` in fixture mode produces the full standard
  figure/table set with no manual post-processing.

### Milestone 10 — Full pipeline integration and reproducibility hardening
- **Objective:** Ensure `scripts/run_all.py` runs the entire pipeline (ingest → panel → event
  study → regression → mean reversion → robustness → reporting) end-to-end in both fixture mode
  and (if real data is available) public-proxy mode, with a single command and a documented
  runtime.
- **Files:** `scripts/run_all.py`, `docs/data_notes.md` finalized, `tests/integration/test_full_pipeline.py`.
- **Tests:** the full-pipeline integration test on fixtures, checked into CI-equivalent (even if
  CI is just a documented local command, not a hosted CI service).
- **Expected outputs:** a clean run log and complete `reports/` directory from a single command.
- **Completion criteria:** a fresh clone + `pip install -e .` + `python scripts/run_all.py
  --mode fixture` reproduces all reported fixture-mode numbers exactly.

### Milestone 11 — Paper, memo, README (writing milestones, not code)
- **Objective:** Populate `reports/paper/`, `reports/memo/`, and top-level `README.md` following
  the outlines in §7, §8, §9, using the real pipeline's outputs.
- **Files:** `reports/paper/*`, `reports/memo/*`, `README.md`.
- **Tests:** none (writing artifact), but a checklist review that every figure/table referenced
  in the paper/memo actually exists in `reports/figures/` and was generated by the pipeline (no
  manually-edited numbers).
- **Expected outputs:** paper draft, one-page (or two-page) memo, polished README.
- **Completion criteria:** every quantitative claim in the paper/memo traces to a specific script
  output file.

---

## 5. Data architecture

### 5.1 Raw data (`data/raw/`)

Untouched downloads, one subfolder per source (`data/raw/prices/`, `data/raw/nav/`,
`data/raw/vix/`, `data/raw/calendars/`), each file stamped with the download date in its
filename. Never modified after download. Treated as a cache — safe to delete and re-run ingestion.

### 5.2 Processed data (`data/processed/`)

Cleaned, date-aligned, per-ticker daily series (price, NAV, dislocation, liquidity measures),
one file per ticker, deterministic given the raw data and code version. Regenerable from
`data/raw/` at any time; not hand-edited.

### 5.3 Panel data (`data/panel/`)

The single final ETF-day panel used by all analysis modules (Milestones 5–8), with stress flags
joined in. This is the one dataset the analysis layer depends on — analysis code never reads
`data/raw/` or `data/processed/` directly.

### 5.4 Fixture data (`data/fixtures/`)

Small, checked-into-git, synthetic or trimmed-real sample data covering a handful of tickers and
a short date range spanning at least one synthetic "stress window," explicitly labeled as
fixture/synthetic in a `data/fixtures/README.md`. Used by:

- `tests/integration/` for pipeline tests,
- `scripts/run_all.py --mode fixture` for anyone cloning the repo without setting up real data
  access.

Fixture data must never be presented as real results in the paper or memo — this is enforced by
a naming convention (`fixtures/` outputs write to `reports/fixture_run/`, not `reports/`) and
called out explicitly in `docs/data_notes.md`.

### 5.5 Modes

- **Offline fixture mode (always available):** `--mode fixture`. No network access. Used for
  development, testing, and demonstrating reproducibility to a reviewer who does not want to
  fetch real data.
- **Public data mode (headline results):** `--mode public`. Uses free public sources per §2.2.
  Produces the real numbers reported in the paper/memo.
- **NAV-enhanced mode (optional upgrade):** `--mode nav-enhanced`. Same interfaces, higher-
  frequency NAV input, unlocked only if such data is obtained; must not be required for any
  headline result.

---

## 6. Testing strategy

### 6.1 Unit tests
One test module per `src/etf_dislocations/` module. Cover: correctness of formulas (Amihud,
Corwin-Schultz, premium/discount, AR(1)/half-life) against hand-computed values on tiny synthetic
inputs; edge cases (missing NAV day, holiday mismatch between ETF and underlying market,
zero-volume day, single-observation regression window).

### 6.2 Integration tests
Full-pipeline tests in fixture mode: ingestion → panel → each analysis module → reporting,
asserting the pipeline runs without error and produces outputs matching a checked-in expected
snapshot (e.g., an expected small results CSV compared with tolerance).

### 6.3 Numerical validation
Where a method has a published closed-form or textbook example (Corwin-Schultz spread estimator,
Amihud ratio, AR(1) half-life, OLS on a known-coefficient synthetic dataset), a test asserts the
implementation reproduces that known value within a stated numerical tolerance. This is the
primary defense against silent formula bugs.

### 6.4 Reproducibility tests
- Deterministic-output test: running the same analysis module twice on the same input produces
  bit-identical output (no unseeded randomness, no wall-clock-dependent values).
- Full-clone test (documented, run manually or in CI-equivalent): a fresh checkout, fresh
  virtualenv, `pip install -e .`, `python scripts/run_all.py --mode fixture` reproduces the
  checked-in expected fixture-mode results exactly.

### 6.5 Standard for "done"
A milestone is not complete until its tests pass and its outputs are traceable — no milestone is
marked complete based on manual inspection alone.

---

## 7. Paper structure (outline only)

1. **Abstract**
2. **Introduction** — motivation, research question, summary of contribution
3. **Institutional background** — how ETF creation/redemption works, why premium/discount should
   normally be arbitraged away, why stress can break this
4. **Literature review** — academic and regulatory literature on ETF premium/discount,
   fixed-income ETF liquidity, March 2020 episode studies, AP behavior
5. **Data** — universe, sources, sample period, data limitations (public-proxy vs. NAV-enhanced)
6. **Methodology** — dislocation measure, liquidity proxies, stress-window definitions,
   event-study design, panel regression specification, mean-reversion/half-life methodology
7. **Results**
   7.1 Event-study results by stress window and asset-class bucket
   7.2 Panel regression results and channel decomposition
   7.3 Mean-reversion / half-life results, calm vs. stress
   7.4 Robustness checks
8. **Discussion** — which channel(s) the evidence supports, economic interpretation, relevance
   to ETF issuers and market structure
9. **Limitations** — honest discussion per §1.6
10. **Conclusion**
11. **References**
12. **Appendix** — full regression tables, additional robustness output, data source details

---

## 8. Executive memo structure (outline only)

Target: 1–2 pages, written for a portfolio manager / product / risk audience (BlackRock/iShares
style), not an academic audience.

1. **Headline finding** (one paragraph, plain English, the single most important number/verdict)
2. **Why this matters** (business/risk relevance to an ETF issuer)
3. **What we did** (2–3 sentence methodology summary, no formulas)
4. **Key evidence** (2–3 charts/tables max, the most decision-relevant ones)
5. **Which channel dominates** (direct answer to the research question)
6. **Caveats an issuer should know about** (condensed version of §1.6)
7. **What we'd want to look at next** (2–3 bullets, ties to §10)

---

## 9. GitHub README outline (structure only)

1. **Title + one-line pitch**
2. **Research question** (one paragraph)
3. **Why it matters** (short, links stress-window/ETF-structure context)
4. **Key result** (one headline chart, one headline number, once real results exist)
5. **How the pipeline works** (short pipeline diagram description: ingest → panel → event
   study/regression/mean-reversion → reporting)
6. **Repository structure** (short version of §3 tree)
7. **Quickstart**
   - clone, install, `run_all.py --mode fixture` (works with zero setup)
   - `run_all.py --mode public` (real data, documents any manual download steps needed)
8. **Data sources and licensing notes** (link to `docs/data_notes.md`)
9. **Reproducibility statement** (fixture mode guarantee, determinism tests)
10. **Limitations** (short version of §1.6)
11. **Paper / memo links** (once written)
12. **License**

---

## 10. Future extensions (explicitly out of MVP scope)

- Intraday iNAV-based analysis if a suitable free/legal data source is found (true NAV-enhanced
  mode, §2.5).
- Direct AP creation/redemption flow analysis if any public proxy for AP activity becomes
  available (e.g., aggregate shares-outstanding changes as a coarse creation/redemption proxy —
  currently only partially reliable and excluded from MVP hypotheses).
- Extension to European/UCITS-listed ETFs (different market-hours structure, different
  regulatory NAV-disclosure regime) as a cross-jurisdiction robustness check.
- Leveraged/inverse ETF premium/discount behavior as a separate, structurally distinct study
  (different arbitrage mechanics, deliberately excluded from the main universe).
- Machine-learning-based dislocation forecasting (deliberately deferred — this project is a
  causal/structural decomposition study, not a forecasting study; conflating the two would dilute
  the core contribution).
- Formal microstructure model of the AP arbitrage decision (option-like exercise framing of
  creation/redemption) as a theoretical companion piece.
- Cross-referencing TRACE bond-level data (§2.3) for a direct, rather than proxied,
  fixed-income-liquidity channel measurement.
- Extending the panel to cover additional stress episodes as they occur after project completion
  (e.g., future rate shocks, credit events), keeping the pipeline as a living monitoring tool.

---

## Constraints (binding on all implementation work)

- Python 3.11 or 3.12 only.
- Public data only; no proprietary vendor feeds (Bloomberg/Refinitiv terminals, paid NAV feeds).
- No aggressive web scraping — respect terms of service, prefer documented download endpoints or
  manual/batch download steps over scraping sponsor sites; document access method and date for
  every source in `docs/data_notes.md`.
- No fabricated or placeholder empirical results anywhere, including in draft paper/memo text —
  every number must trace to a pipeline run.
- The pipeline must always be reproducible offline via `data/fixtures/` and
  `scripts/run_all.py --mode fixture`.
- Research quality and reproducibility take priority over runtime performance; do not
  micro-optimize at the expense of clarity or correctness.
- Research-first: the dashboard/reporting layer exists to serve the research findings, not the
  reverse.
- Clean modular architecture per §3; no analysis logic inside `scripts/` or `notebooks/`.
- Every limitation in §1.6 must be explicitly and honestly reflected in the paper (§7) and memo
  (§8) — this project is judged on research honesty, not on overstating results.
