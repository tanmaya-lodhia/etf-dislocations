"""Generate the synthetic offline fixture dataset.

Writes deterministic (seeded) daily OHLCV CSVs to data/fixtures/prices/ for a
subset of the universe spanning the asset-class buckets. The series include a
synthetic high-volatility stretch so later stress-detection milestones have
something to find in fixture mode.

Run once and commit the output; tests and fixture-mode runs read the committed
files rather than regenerating them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]

SEED = 20260710
N_DAYS = 130
START = "2024-01-02"
# Trading days 60-80 get elevated volatility and volume: a synthetic "stress
# window" clearly labelled as such in the fixtures README.
STRESS_START, STRESS_END = 60, 80

# ticker -> (start price, annualised vol, typical daily share volume)
FIXTURE_SPECS = {
    "SPY": (470.0, 0.12, 80e6),
    "EFA": (75.0, 0.14, 18e6),
    "LQD": (108.0, 0.08, 25e6),
    "HYG": (77.0, 0.10, 45e6),
    "TLT": (95.0, 0.15, 30e6),
}

# ticker -> (calm premium/discount noise sd, mean stress-window discount).
# Bond funds get a materially wider stress discount than equity funds so the
# fixture panel exhibits the cross-sectional pattern later milestones test on.
NAV_SPECS = {
    "SPY": (0.0003, -0.001),
    "EFA": (0.0010, -0.004),
    "LQD": (0.0015, -0.015),
    "HYG": (0.0020, -0.020),
    "TLT": (0.0008, -0.003),
}


def make_ticker_frame(
    rng: np.random.Generator, start_price: float, ann_vol: float, base_volume: float
) -> pd.DataFrame:
    dates = pd.bdate_range(START, periods=N_DAYS)
    daily_vol = np.full(N_DAYS, ann_vol / np.sqrt(252))
    daily_vol[STRESS_START:STRESS_END] *= 3.0

    rets = rng.normal(0.0002, daily_vol)
    close = start_price * np.cumprod(1 + rets)

    intraday = np.abs(rng.normal(0, daily_vol))
    open_ = close * (1 + rng.normal(0, daily_vol / 2))
    high = np.maximum(open_, close) * (1 + intraday)
    low = np.minimum(open_, close) * (1 - intraday)

    vol_mult = np.ones(N_DAYS)
    vol_mult[STRESS_START:STRESS_END] = 2.5
    volume = (base_volume * vol_mult * rng.lognormal(0, 0.3, N_DAYS)).round()

    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": open_.round(4),
            "high": high.round(4),
            "low": low.round(4),
            "close": close.round(4),
            "volume": volume.astype(int),
        }
    )


def make_nav_frame(
    rng: np.random.Generator,
    prices: pd.DataFrame,
    noise_sd: float,
    stress_discount: float,
) -> pd.DataFrame:
    """Synthetic NAV: close divided by (1 + premium), where the premium is
    AR(1) noise in calm periods and shifts to a persistent discount in the
    synthetic stress window."""
    n = len(prices)
    target = np.zeros(n)
    target[STRESS_START:STRESS_END] = stress_discount

    prem = np.zeros(n)
    for t in range(1, n):
        prem[t] = 0.7 * prem[t - 1] + 0.3 * target[t] + rng.normal(0, noise_sd)

    nav = prices["close"].to_numpy() / (1 + prem)
    return pd.DataFrame({"date": prices["date"], "nav": nav.round(4)})


def make_vix_frame(rng: np.random.Generator) -> pd.DataFrame:
    dates = pd.bdate_range(START, periods=N_DAYS)
    level = np.full(N_DAYS, 14.0)
    level[STRESS_START:STRESS_END] = 35.0
    vix = level * rng.lognormal(0, 0.08, N_DAYS)
    return pd.DataFrame(
        {"date": dates.strftime("%Y-%m-%d"), "vix": vix.round(2)}
    )


def main() -> int:
    fixtures = REPO_ROOT / "data" / "fixtures"
    prices_dir = fixtures / "prices"
    nav_dir = fixtures / "nav"
    prices_dir.mkdir(parents=True, exist_ok=True)
    nav_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(SEED)
    for ticker, (price, vol, share_vol) in FIXTURE_SPECS.items():
        df = make_ticker_frame(rng, price, vol, share_vol)
        df.to_csv(prices_dir / f"{ticker}.csv", index=False)
        print(f"wrote {prices_dir / (ticker + '.csv')} ({len(df)} rows)")

        noise_sd, stress_disc = NAV_SPECS[ticker]
        nav = make_nav_frame(rng, df, noise_sd, stress_disc)
        nav.to_csv(nav_dir / f"{ticker}.csv", index=False)
        print(f"wrote {nav_dir / (ticker + '.csv')} ({len(nav)} rows)")

    vix = make_vix_frame(rng)
    vix.to_csv(fixtures / "vix.csv", index=False)
    print(f"wrote {fixtures / 'vix.csv'} ({len(vix)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
