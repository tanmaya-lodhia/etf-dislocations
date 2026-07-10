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


def main() -> int:
    out_dir = REPO_ROOT / "data" / "fixtures" / "prices"
    out_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(SEED)
    for ticker, (price, vol, share_vol) in FIXTURE_SPECS.items():
        df = make_ticker_frame(rng, price, vol, share_vol)
        path = out_dir / f"{ticker}.csv"
        df.to_csv(path, index=False)
        print(f"wrote {path} ({len(df)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
