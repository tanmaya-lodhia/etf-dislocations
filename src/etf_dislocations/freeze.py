"""Freeze a built panel to an immutable, versioned snapshot.

A live source (Yahoo, sponsor NAV downloads) changes day to day, so a paper
whose numbers are regenerated against a live fetch is not reproducible even
when the pipeline itself is. Freezing writes the panel to a dated Parquet
file under data/frozen/, plus a sibling JSON provenance record, and refuses
to silently overwrite an existing snapshot: once written, a snapshot is
meant to be permanent.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from . import __version__

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProvenanceRecord:
    dataset: str
    mode: str
    price_source: str
    retrieved: str
    date_range: tuple[str, str]
    tickers: tuple[str, ...]
    n_rows: int
    package_version: str
    notes: str | None = None

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "mode": self.mode,
            "price_source": self.price_source,
            "retrieved": self.retrieved,
            "date_range": list(self.date_range),
            "tickers": list(self.tickers),
            "n_rows": self.n_rows,
            "package_version": self.package_version,
            "notes": self.notes,
        }


def build_provenance(
    panel: pd.DataFrame,
    mode: str,
    price_source: str,
    retrieved: str,
    notes: str | None = None,
) -> ProvenanceRecord:
    """Summarise a panel into a provenance record (SPEC.md section 7, Data
    provenance). `retrieved` is passed in rather than computed here so the
    caller controls the one non-deterministic input (today's date)."""
    if panel.empty:
        raise ValueError("Cannot freeze an empty panel")
    dates = pd.to_datetime(panel["date"])
    return ProvenanceRecord(
        dataset="etf_day_panel",
        mode=mode,
        price_source=price_source,
        retrieved=retrieved,
        date_range=(dates.min().date().isoformat(), dates.max().date().isoformat()),
        tickers=tuple(sorted(panel["ticker"].unique())),
        n_rows=len(panel),
        package_version=__version__,
        notes=notes,
    )


def freeze_panel(
    panel: pd.DataFrame,
    out_dir: Path,
    provenance: ProvenanceRecord,
    name: str | None = None,
    force: bool = False,
) -> tuple[Path, Path]:
    """Write the panel and its provenance record to data/frozen/.

    Returns (parquet_path, provenance_path). Refuses to overwrite an
    existing snapshot unless force=True, since a frozen snapshot is meant to
    be permanent once a paper cites it.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if name is None:
        name = f"etf_panel_{provenance.retrieved}"

    parquet_path = out_dir / f"{name}.parquet"
    provenance_path = out_dir / f"{name}.provenance.json"

    if not force:
        existing = [p for p in (parquet_path, provenance_path) if p.exists()]
        if existing:
            raise FileExistsError(
                f"Snapshot already exists: {[str(p) for p in existing]} "
                f"(pass force=True / --force to intentionally replace it)"
            )

    panel.to_parquet(parquet_path, index=False)
    provenance_path.write_text(
        json.dumps(provenance.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    logger.info(
        "Froze %d rows to %s (tickers=%s, range=%s to %s)",
        provenance.n_rows,
        parquet_path,
        ",".join(provenance.tickers),
        *provenance.date_range,
    )
    return parquet_path, provenance_path


def load_frozen_panel(parquet_path: Path) -> tuple[pd.DataFrame, dict]:
    """Load a frozen panel and its provenance record."""
    if not parquet_path.is_file():
        raise FileNotFoundError(f"Frozen snapshot not found: {parquet_path}")
    provenance_path = parquet_path.parent / f"{parquet_path.stem}.provenance.json"
    if not provenance_path.is_file():
        raise FileNotFoundError(
            f"Provenance record not found: {provenance_path} "
            f"(every frozen snapshot must have one)"
        )
    panel = pd.read_parquet(parquet_path)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    return panel, provenance
