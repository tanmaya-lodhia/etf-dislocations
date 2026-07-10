"""Standard figure set. Non-interactive backend; figures are written to
disk, never shown. No analysis logic here.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

logger = logging.getLogger(__name__)


def plot_event_window(
    bucket_means: pd.DataFrame, event: str, out_path: Path
) -> Path:
    """Average abnormal premium/discount by event day, one line per asset
    class bucket, for a single event."""
    data = bucket_means[bucket_means["event"] == event]
    if data.empty:
        raise ValueError(f"No bucket means for event {event!r}")

    fig, ax = plt.subplots(figsize=(9, 5))
    for bucket, grp in data.groupby("bucket"):
        grp = grp.sort_values("tau")
        ax.plot(grp["tau"], grp["mean_abnormal"] * 1e4, label=bucket)

    ax.axhline(0, color="black", linewidth=0.8)
    ax.axvline(0, color="grey", linewidth=0.8, linestyle="--")
    ax.set_xlabel("Trading days relative to event start")
    ax.set_ylabel("Mean abnormal premium/discount (bp)")
    ax.set_title(f"Abnormal ETF dislocation around {event}")
    ax.legend(title="Bucket", fontsize=8)
    fig.tight_layout()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    logger.info("Wrote %s", out_path)
    return out_path
