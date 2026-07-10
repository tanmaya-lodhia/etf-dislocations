"""Tier-1 canonical stress windows (SPEC.md section 2.7).

The event list is pre-registered in config/stress_windows.yaml. This module
only parses and applies it; the windows themselves are never derived from
data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from ..config import repo_root


@dataclass(frozen=True)
class StressEvent:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp


def load_tier1_events(path: Path | None = None) -> tuple[StressEvent, ...]:
    """Load and validate the Tier-1 event windows."""
    if path is None:
        path = repo_root() / "config" / "stress_windows.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    events = []
    seen: set[str] = set()
    for item in cfg["events"]:
        name = str(item["name"])
        start = pd.Timestamp(item["start"])
        end = pd.Timestamp(item["end"])
        if end < start:
            raise ValueError(f"Event {name}: end {end.date()} before start {start.date()}")
        if name in seen:
            raise ValueError(f"Duplicate event name: {name}")
        seen.add(name)
        events.append(StressEvent(name=name, start=start, end=end))

    if not events:
        raise ValueError("No Tier-1 events configured")
    ordered = sorted(events, key=lambda e: e.start)
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt.start <= prev.end:
            raise ValueError(
                f"Events {prev.name} and {nxt.name} overlap; windows must be disjoint"
            )
    return tuple(ordered)


def event_for_dates(
    dates: pd.DatetimeIndex | pd.Series,
    events: tuple[StressEvent, ...],
) -> pd.Series:
    """Map each date to the name of the Tier-1 event containing it, else NA.

    Windows are disjoint (enforced at load), so the mapping is unambiguous.
    """
    if isinstance(dates, pd.Series):
        values = pd.DatetimeIndex(dates)
        index = dates.index
    else:
        values = dates
        index = dates

    out = pd.Series(pd.NA, index=index, dtype="string", name="tier1_event")
    normalized = values.normalize()
    for ev in events:
        mask = (normalized >= ev.start) & (normalized <= ev.end)
        out[mask] = ev.name
    return out
