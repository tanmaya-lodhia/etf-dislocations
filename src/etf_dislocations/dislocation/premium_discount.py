"""Premium/discount: the core dislocation measure (SPEC.md section 2.8).

Positive values mean the ETF trades above the value of its holdings
(premium); negative values mean a discount. Both the simple and log variants
are computed; the log variant is the robustness alternative (section 2.11).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def premium_discount(close: pd.Series, nav: pd.Series) -> pd.Series:
    """Simple premium/discount: (price - NAV) / NAV, on the close's index.

    NAV is aligned to the price dates; days without a NAV observation are
    NaN. Non-positive NAVs are treated as missing.
    """
    aligned = nav.reindex(close.index)
    aligned = aligned.mask(aligned <= 0)
    return ((close - aligned) / aligned).rename("premium_discount")


def log_premium_discount(close: pd.Series, nav: pd.Series) -> pd.Series:
    """Log premium/discount: ln(price / NAV), on the close's index."""
    aligned = nav.reindex(close.index)
    aligned = aligned.mask(aligned <= 0)
    return np.log(close / aligned).rename("log_premium_discount")
