# Live-data validation and data-availability audit

Date: 2026-07-10. Scope: verify public-mode ingestion against live endpoints,
audit NAV availability by sponsor, validate the premium/discount formula
against sponsor-published numbers, and run the controlled pipeline on a
small representative sample. No methodology changes, no universe expansion,
no paper/memo writing. See `docs/etf_data_availability.csv` for the
machine-readable classification table this audit produced.

**Terminology note:** SPEC.md section 2.5 defines "NAV-enhanced mode"
strictly as an *intraday* iNAV upgrade. Nothing found this session is
intraday. Where this audit and the availability CSV say a ticker is
"NAV-enhanced ready," it means *automated daily NAV is available*, which is
a lesser claim than SPEC's intraday NAV-enhanced mode — it upgrades a ticker
from "manual CSV required" to "reproducible from a documented endpoint,"
nothing more.

## Representative sample

SPY (equity), EEM (EM equity), TLT (rates), LQD (IG credit), HYG (HY
credit), GLD (gold, for NAV-formula validation only — GLD is a physical
commodity trust and is *not* in the registered universe per SPEC.md section
1.5; it was never added to `config/universe.yaml`).

## Phase 1: Public price ingestion

### Stooq is currently non-functional (site-wide anti-bot challenge)

Every Stooq endpoint tested — the main site, quote pages, and the CSV
download endpoint used by `ingest_prices.py` for both prices and VIX —
returns HTTP 200 with an HTML page containing a client-side JavaScript
proof-of-work challenge (`"requires JavaScript to verify your browser"`),
regardless of User-Agent. This is new since the ingestion module was built;
it is not a symbol-mapping problem, and no combination of headers changed
the result. Solving the challenge programmatically would mean defeating
Yahoo/Stooq's bot detection, which this project does not do (see
Constraints: no aggressive scraping, no evasion).

**Fix applied:** `parse_stooq_csv` now detects this specific page (matching
on the marker string) and raises a distinct, actionable error instead of the
generic "not a Stooq CSV" message, so a future session doesn't waste time
suspecting the symbol mapping. Stooq remains the configured default source
(no silent substitution); nothing was removed.

### Yahoo Finance chart API — confirmed working, added as an opt-in fallback

`https://query1.finance.yahoo.com/v8/finance/chart/{symbol}` (the endpoint
the `yfinance` library wraps — one of the sources SPEC.md section 2.2 names
as acceptable) returned HTTP 200 with real JSON for all six representative
tickers plus `^VIX`, no key required, one GET per symbol.

Checked directly against a 2-year pull for SPY and 10-year pulls for all six
representative tickers via the newly added `ingest_prices_yahoo` /
`parse_yahoo_chart_json`:

| Check | Result |
|---|---|
| Endpoint accessibility | 200 OK for SPY, EEM, TLT, LQD, HYG, GLD, ^VIX |
| Date coverage | 2,514 rows per ticker, exactly matching NYSE (`XNYS`) session count for the 2016-07-11 to 2026-07-10 window (`pandas_market_calendars`) — zero missing trading days |
| Ticker conventions | Yahoo symbols equal the project's own tickers 1:1, no suffix (`^VIX` for VIX) |
| Adjusted vs. unadjusted | Yahoo returns both a raw `close` and a separate `adjclose` (dividend-adjusted); this project ingests raw `close` only, matching the existing Stooq convention documented for the same reason (same-day price levels, not long-horizon returns) |
| OHLCV completeness | 0 duplicate dates, 0 non-positive prices, 0 negative/NaN volume across all 5 in-universe tickers tested |
| Zero/implausible volume | None found for the 5 tested ETFs. VIX itself legitimately has `volume = 0` on essentially every day (it's an index, not traded) — expected, not a defect |
| Missing observations | VIX: 95 of 2,610 raw bars were entirely null (placeholder bars Yahoo emits on US market holidays — verified against known holidays: 2016-09-05 Labor Day, 2016-11-24 Thanksgiving, 2016-12-26, 2017-01-02, 2017-01-16 MLK Day). Correctly dropped by the existing `clean_prices` validation; no code change needed |
| Timezone/date alignment | Timestamps are UTC seconds at the session's local time (13:30 or 14:30 UTC depending on DST, i.e. 9:30 ET); converting via UTC date never rolls to the wrong calendar day for any US-market ticker, since the session always opens in the UTC morning. Documented in the parser's docstring rather than silently assumed, since a ticker on a market with a very different UTC offset could roll over |
| Corporate-action handling | Yahoo's `events` block carries a `dividends` series (splits under a separate key); this project does not currently ingest or net out either — same limitation as Stooq's unadjusted-close convention, already documented |
| Deterministic ordering | `clean_prices` sorts and dedupes by date; identical fetch text produces byte-identical processed output (verified via the Phase 4 double-run) |

**Second-source comparison:** not practically achievable this session
without violating the no-account-creation rule (Nasdaq Data Link/Quandl's
free EOD tier requires a key) or resorting to a JS-challenge bypass (Stooq).
The closest available independent cross-check was Phase 3's comparison
against SPDR's own sponsor-published NAV/premium-discount data (see below),
which is a genuinely different data source and methodology, not just a
second price feed.

**Fix applied:** added `fetch_yahoo_chart_json` / `parse_yahoo_chart_json` /
`ingest_prices_yahoo` / `ingest_vix_yahoo` to `data/ingest_prices.py` and
`data/ingest_vix.py`, and a `yahoo:` block to `config/data_sources.yaml`.
Wired into the CLI as `etf-dislocations ingest --price-source yahoo`
(**default remains `stooq`** — this is an explicit opt-in, not a silent
substitution).

## Phase 2: NAV data audit

No sponsor was found offering a keyless, documented **intraday** iNAV feed.
For daily NAV history, sponsors split cleanly into two groups:

**State Street (SPDR)** publishes a stable, keyless daily NAV-history export
per fund, discoverable directly in the fund page's static HTML (no
JavaScript execution needed to find it — the page embeds the file path as a
plain `href`, e.g. `.../navhist-us-en-spy.xlsx`):

- Confirmed working (HTTP 200, genuine `.xlsx`) 2026-07-10 for **SPY, XLF,
  XLE, XLK, JNK** — every SPDR-sponsored ticker in the registered universe.
- Format: `navhist` sheet, 3-row header block (fund name, ticker, blank),
  then `Date, NAV, Shares Outstanding, Total Net Assets`, then a disclaimer
  footer. SPY's file: 5,689 clean rows, **2003-12-01 to present** (today,
  same-day) — comfortably covers all four Tier-1 stress windows.
- **Bonus finding:** the file also carries daily **Shares Outstanding**,
  which SPEC.md section 2.6 lists as an optional improvement over the
  volume-only turnover proxy currently implemented (`liquidity/turnover.py`
  explicitly notes shares outstanding "are not reliably available from free
  sources" — that statement is no longer true for SPDR-sponsored tickers).
  Not implemented this session (out of scope — flagged as a future
  extension candidate, not acted on).
- SPDR Gold Shares (`spdrgoldshares.com`, GLD/GLDM) additionally publishes a
  **sponsor-calculated premium/discount field** back to 2004-11-18, used
  only for Phase 3 validation below, not ingested as a data source (GLD is
  out of universe).

**Fix applied:** added `fetch_spdr_navhist_xlsx` / `parse_spdr_navhist_xlsx`
to `data/ingest_nav.py`, a `spdr_navhist:` block to
`config/data_sources.yaml` (scoped to exactly SPY/XLF/XLE/XLK/JNK), and
wired it into `ingest_nav()` as an **automatic fallback used only when no
manual `data/raw/nav/<TICKER>.csv` is present** — a manually placed file
always wins, so this never silently overrides a user correction.

**iShares (BlackRock)** — EEM, TLT, LQD, HYG, IVV, IEF, SHY, AGG, EFA, and
the gold trust IAU — could not be resolved to a keyless automated endpoint
this session. The current iShares fund pages are a client-side-rendered SPA
(Astro-based); the static HTML contains no `.xlsx`/`.csv`/`.ajax` links at
all, only a placeholder for the current point-in-time NAV
(`fundHeader-navAmount`). The historical-NAV download is almost certainly
served by an internal API triggered by JavaScript after page load, which
this session could not observe (the Chrome browser tool was not connected —
see Blockers below). Guessing at the legacy `.ajax?fileType=csv&fileName=...`
pattern from public knowledge returned the SPA's fallback HTML page, not
data, confirming the old pattern no longer works and further guessing was
not attempted (would edge into exactly the endpoint-probing this project's
"no aggressive scraping" rule is meant to avoid).

**Vanguard (VWO, BND)** — not probed this session (out of the 6-ticker
representative sample); still documented as manual-download-only per the
existing `docs/data_notes.md`, unverified either way.

**Fix applied (documentation only):** `QQQ`'s sponsor was missing entirely
from the sponsor-mapping table in `docs/data_notes.md` before this audit
(the table listed iShares, SPDR, and Vanguard groups covering 16 of 17
universe tickers; QQQ — Invesco QQQ Trust — was omitted). Corrected.

## Phase 3: NAV validation

### SPY: computed premium/discount vs. real market data

Aligned Yahoo `close` against SPDR's automated `navhist` NAV, 2016-07-11 to
2026-07-09 (2,513 matched days; one Yahoo price date had no matching NAV row
— the most recent day, a T+1 publication lag, not a data error):

| Statistic | Value |
|---|---|
| Mean premium/discount | +0.28 bp |
| Median \|premium/discount\| | 1.76 bp |
| Mean \|premium/discount\| | 2.51 bp |
| Max \|premium/discount\| | 90.0 bp (2025-04-09 — the April 2025 tariff-driven volatility spike; a real, plausible market event, not a data artifact) |

These magnitudes are exactly what a well-arbitraged, cash-created domestic
equity ETF should show: near-zero, tightly distributed, with the single
largest excursion landing on a known real stress day. This is a strong
plausibility check but a *weak independence* check, noted honestly: SPY's
official NAV and its 4pm closing price are struck from close to the same
underlying inputs, so near-agreement is partly mechanical, not solely proof
that this project's formula is bug-free.

### GLD: computed premium/discount vs. sponsor-published premium/discount

GLD's own historical archive publishes its *own* calculated
premium/discount (mid-point of bid/ask at 4:15pm NYT vs. its own indicative
value at 4:15pm NYT) — a genuinely independent check of this project's
`(price - NAV) / NAV` formula against someone else's implementation of the
same concept, 2004-11-18 to 2026-07-09 (5,438 rows).

**First attempt (naive, wrong) — investigate discrepancies rather than
force agreement:** comparing GLD's 4:15pm mid-point price against its
*10:30am* NAV/share (a timestamp mismatch introduced by this ad hoc check,
not by the pipeline) produced a median absolute discrepancy of 0.29
percentage points and a max of 6.67 points versus the sponsor's own number —
large enough to investigate rather than accept.

**Root cause, confirmed:** NAV timing convention. Re-running the comparison
using the sponsor's own matched-timestamp fields (4:15pm mid-point price vs.
4:15pm indicative value, exactly what the sponsor's published number uses)
collapses the discrepancy to:

| Statistic | Value |
|---|---|
| Median absolute discrepancy | 0.00019 percentage points (≈0.02 bp) |
| Mean absolute discrepancy | 0.0049 percentage points (≈0.5 bp) |
| Max absolute discrepancy | 2.77 percentage points, a single row (2005-08-02, one of 5,438) — an apparent one-off anomaly in the sponsor's own 2005-era file, not investigated further given it is a single point in a 21-year series and does not change the conclusion |

**Conclusion:** once the timestamp convention is matched, this project's
premium/discount formula reproduces an independently sponsor-published
number almost exactly. **No formula change was made** — the investigation
correctly identified the input timing as the source of the initial gap, per
the instruction not to alter formulas merely to force agreement.

As a separate, purely descriptive data point (not an empirical conclusion
about the project's research question — GLD is out of universe and this is
one ticker): using this project's actual daily-close-vs-NAV convention, GLD
shows a much wider typical premium/discount (median ≈31 bp, mean ≈47 bp,
max ≈678 bp) than SPY — plausible for a physically-backed commodity trust,
but not asserted as a finding.

## Phase 4: Controlled pipeline run

Ran `etf-dislocations run-all --mode public` on the pre-registered subset
{SPY, EEM, TLT, LQD, HYG} (all already in `config/universe.yaml` — nothing
added to the universe; GLD was excluded from this phase precisely because
it is not a universe member). Prices: Yahoo, all five. NAV: SPY only
(automated SPDR); EEM/TLT/LQD/HYG correctly show `premium_discount = NaN`
throughout (public-proxy-only until a manual NAV file is supplied) — the
existing warning-and-continue behavior in `panel.py` and `cli.py` handled
this exactly as designed, no change needed.

Panel built: 12,570 rows (5 tickers x 2,514 days), 2016-07-11 to
2026-07-10. EEM correctly flagged 117/2,514 stale-pricing days (`XHKG`
closed) — the international-market-hours logic exercised on real data for
the first time. 305 Tier-1 rows fired (Dec 2018 selloff, COVID 2020, and the
2022 rates selloff all fall inside this 10-year Yahoo window; the 2015 flash
crash does not — Yahoo's chart API was called with `range=10y`, so it starts
2016-07-11, after that event. Not a defect; a scope note for whoever runs
the full-universe pull, who should request a longer range or a fixed
`period1`/`period2` window instead of a relative range).

**Two real bugs surfaced and fixed** by running on this genuinely
NAV-sparse real sample (fixture data, with NAV for every ticker, could never
have caught these):

1. **Rank-deficient design matrix.** With only SPY carrying non-null
   `premium_discount`, every other ticker's `abs_premium_discount` (the
   regression's dependent variable) was NaN, so `dropna()` left a
   single-entity sample in which `stale_pricing` (never true for a domestic
   ticker) became a constant column — colliding with the intercept and
   crashing `PanelOLS` with an opaque "exog does not have full column rank"
   error. **Fixed** in `analysis/panel_regression.py`: `run_specification`
   now detects and drops zero-variance features per call (mirroring a
   pattern that already existed only in the robustness module, now shared).
2. **Degenerate two-way fixed effects.** The same single-entity sample made
   `two_way_fixed_effects` mathematically inestimable (one entity has no
   cross-sectional heterogeneity for an entity effect to remove), which
   crashed deep inside `linearmodels` with an unrelated-looking "No objects
   to concatenate" error. **Fixed:** `run_specification` now raises a clear,
   specific error when `entity_effects`/`time_effects` is requested with
   fewer than 2 entities/periods in the complete-case sample, and
   `run_panel_regressions` skips (with a warning) any specification that
   isn't estimable rather than aborting the whole regression stage — the
   other, estimable specifications still run and are reported.

With both fixes, `run-all --mode public` completed end-to-end (exit 0) on
real data, producing all 13 expected outputs (event study, panel
regression — 2 of 3 specs estimable given the single-entity NAV sample,
mean reversion, robustness, manifest).

**Illustrative real numbers** (not an empirical conclusion — one ticker,
partial sample; reported only to show the pipeline computes something
plausible on genuine data): SPY's COVID-2020 event-study window shows a max
abnormal dislocation of 80.0 bp, in line with widely reported March 2020 SPY
premium/discount behavior; SPY's daily premium/discount AR(1) fit gives a
same-day half-life in both calm and stress regimes, consistent with SPY
being one of the most tightly arbitraged ETFs in existence.

**Determinism:** ran the full pipeline twice into separate output
directories. Every CSV and the `run_manifest.json` (including its embedded
SHA-256 hashes) were byte-identical between the two runs; file lists
matched exactly. Real-data reproducibility confirmed, not just fixture-mode.

## Discrepancies vs. SPEC.md assumptions

- SPEC.md section 2.2 names `yfinance` / Stooq / Nasdaq Data Link as
  acceptable price sources without flagging any as unreliable; Stooq is
  currently unusable programmatically (see Phase 1). Yahoo (the source
  `yfinance` wraps) is confirmed working and is now available as an
  explicit opt-in.
- SPEC.md section 5.1 describes `data/raw/vix/` as a subfolder; the actual
  (pre-existing, not introduced this session) `ingest_vix`/`ingest_vix_yahoo`
  code writes the raw VIX cache file directly under `data/raw/`, not
  `data/raw/vix/`. Noted here rather than fixed — it's a cosmetic
  raw-cache-layout mismatch, not a correctness issue, and changing it would
  touch already-tested, working code for no functional benefit.
- SPEC.md's Milestone-1 "risk flag" anticipated exactly the situation found
  here: free daily-NAV availability varies by sponsor. That risk is now
  resolved for State Street/SPDR-sponsored tickers (automated) and remains
  open for iShares/Vanguard-sponsored tickers (manual only).

## Final classification

See `docs/etf_data_availability.csv` for the full table. Summary for the
six representative tickers:

| Ticker | Price | NAV | Classification |
|---|---|---|---|
| SPY | live (Yahoo) | live (SPDR navhist) | NAV-enhanced ready (daily) |
| EEM | live (Yahoo) | none found | manual NAV file required |
| TLT | live (Yahoo) | none found | manual NAV file required |
| LQD | live (Yahoo) | none found | manual NAV file required |
| HYG | live (Yahoo) | none found | manual NAV file required |
| GLD | live (Yahoo) | live (SPDR archive) | NAV-enhanced ready (daily) — **not in universe**, audit-only |

No sample ticker is `unsupported` — every one has at least a working price
feed and either an automated or a documented manual NAV path.

## Is the project ready for a full-universe real-data run?

**Not yet — public-mode price ingestion needs one small operational choice,
and 12 of 17 universe tickers still need a manual NAV step.** Specifically:

**Blockers:**

1. **Stooq is the configured default and is currently non-functional.**
   Either (a) explicitly run with `--price-source yahoo` for the full
   universe, or (b) periodically re-check whether Stooq's challenge has
   lifted. No code blocker — this is an operational decision, already
   supported.
2. **12 of 17 universe tickers have no confirmed automated NAV path:**
   iShares (IVV, EFA, EEM, LQD, AGG, HYG, TLT, IEF, SHY — 9 tickers),
   Vanguard (VWO, BND — 2 tickers, not probed this session), and Invesco
   (QQQ — 1 ticker). A future session with the Chrome browser tool
   connected should open one iShares fund page, trigger the real NAV/Price
   History download, capture the actual request URL from the network
   panel, and add it to `data_sources.yaml` the same way the SPDR endpoint
   was added here; Vanguard and Invesco are entirely unexamined and would
   need the same treatment. Until then, all 12 need a manually downloaded
   `data/raw/nav/<TICKER>.csv` per `docs/data_notes.md`, exactly as already
   documented.
3. **The Yahoo pull used a 10-year relative range**, which misses the 2015
   flash crash entirely. A full-universe run should request an explicit
   date range (e.g. `period1`/`period2` params) covering at least
   2015-01-01, not `range=10y`.
4. **The browser tool was unavailable this session** (Chrome extension not
   connected), which is why iShares' JS-rendered download mechanism could
   not be directly observed. This is an environment/tooling gap, not a data
   or code gap.

**Not blockers** (already resolved this session): price ingestion works
end-to-end via the Yahoo fallback for all 17 universe tickers (spot-checked
symbol-reachability for all of them; deep-validated 5); the panel,
event-study, regression, mean-reversion, and robustness stages all run
correctly on real data, including on a NAV-sparse sample, after the two
fixes above; the full pipeline is reproducible bit-for-bit on live data.
