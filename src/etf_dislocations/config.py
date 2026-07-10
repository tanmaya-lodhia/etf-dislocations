"""Configuration loading.

All tunable parameters live in YAML files under config/ at the repository
root. Code receives parsed, validated objects and never reads YAML ad hoc.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


def repo_root() -> Path:
    """Return the repository root (the directory containing config/).

    Resolved relative to this file so it works regardless of the caller's
    working directory.
    """
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LiquiditySettings:
    rolling_window: int
    annualisation_days: int


@dataclass(frozen=True)
class Settings:
    fixtures_dir: Path
    raw_dir: Path
    processed_dir: Path
    panel_dir: Path
    liquidity: LiquiditySettings


def load_settings(path: Path | None = None) -> Settings:
    """Load pipeline settings from config/settings.yaml.

    Relative paths in the file are resolved against the repository root.
    """
    root = repo_root()
    if path is None:
        path = root / "config" / "settings.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    paths = cfg["paths"]
    liq = cfg["liquidity"]

    def _resolve(p: str) -> Path:
        candidate = Path(p)
        return candidate if candidate.is_absolute() else root / candidate

    rolling_window = int(liq["rolling_window"])
    annualisation_days = int(liq["annualisation_days"])
    if rolling_window < 2:
        raise ValueError(f"rolling_window must be >= 2, got {rolling_window}")
    if annualisation_days < 1:
        raise ValueError(
            f"annualisation_days must be >= 1, got {annualisation_days}"
        )

    return Settings(
        fixtures_dir=_resolve(paths["fixtures"]),
        raw_dir=_resolve(paths["raw"]),
        processed_dir=_resolve(paths["processed"]),
        panel_dir=_resolve(paths["panel"]),
        liquidity=LiquiditySettings(
            rolling_window=rolling_window,
            annualisation_days=annualisation_days,
        ),
    )
