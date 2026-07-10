"""Join Tier-1 and Tier-2 stress flags onto the ETF-day panel.

Kept separate from panel construction: the panel measures what happened,
the stress layer classifies when it happened. Later milestones consume the
combined frame.
"""

from __future__ import annotations

import logging

import pandas as pd

from .tier1_events import StressEvent, event_for_dates
from .tier2_rule import Tier2Rules, pd_vol_stress_days, vix_stress_days

logger = logging.getLogger(__name__)

STRESS_COLUMNS = [
    "tier1_event",
    "tier1_stress",
    "vix_stress",
    "pd_vol_stress",
    "tier2_stress",
]


def add_stress_flags(
    panel: pd.DataFrame,
    events: tuple[StressEvent, ...],
    rules: Tier2Rules,
) -> pd.DataFrame:
    """Return the panel with STRESS_COLUMNS appended.

    Tier-1 flags depend only on the calendar. The VIX rule is computed once
    on the date-level VIX series and broadcast to all tickers; the
    premium/discount volatility rule is computed per ticker. Dates without
    VIX data are never VIX-flagged.
    """
    out = panel.copy()

    out["tier1_event"] = event_for_dates(out["date"], events).values
    out["tier1_stress"] = out["tier1_event"].notna()

    by_date = (
        out.loc[:, ["date", "vix"]]
        .drop_duplicates("date")
        .set_index("date")["vix"]
        .sort_index()
        .dropna()
    )
    if by_date.empty:
        out["vix_stress"] = False
    else:
        flags = vix_stress_days(by_date, rules)
        out["vix_stress"] = (
            out["date"].map(flags).astype("boolean").fillna(False).astype(bool)
        )

    out["pd_vol_stress"] = (
        out.groupby("ticker", sort=False)["premium_discount"]
        .transform(lambda s: pd_vol_stress_days(s, rules))
        .astype(bool)
    )

    out["tier2_stress"] = out["vix_stress"] | out["pd_vol_stress"]

    logger.info(
        "Stress flags: %d tier1 rows, %d vix-stress rows, %d pd-vol-stress rows",
        int(out["tier1_stress"].sum()),
        int(out["vix_stress"].sum()),
        int(out["pd_vol_stress"].sum()),
    )
    return out
