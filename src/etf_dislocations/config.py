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
    volume_window: int = 60


@dataclass(frozen=True)
class StooqConfig:
    url_template: str
    vix_symbol: str
    price_symbols: dict[str, str]


@dataclass(frozen=True)
class NavConfig:
    date_columns: tuple[str, ...]
    nav_columns: tuple[str, ...]


@dataclass(frozen=True)
class DataSources:
    stooq: StooqConfig
    nav: NavConfig
    foreign_calendars: dict[str, str]


def load_data_sources(path: Path | None = None) -> DataSources:
    """Load public data-source configuration from config/data_sources.yaml."""
    if path is None:
        path = repo_root() / "config" / "data_sources.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    stooq = cfg["stooq"]
    nav = cfg["nav"]
    return DataSources(
        stooq=StooqConfig(
            url_template=str(stooq["url_template"]),
            vix_symbol=str(stooq["vix_symbol"]),
            price_symbols={
                str(k).upper(): str(v) for k, v in stooq["price_symbols"].items()
            },
        ),
        nav=NavConfig(
            date_columns=tuple(nav["date_columns"]),
            nav_columns=tuple(nav["nav_columns"]),
        ),
        foreign_calendars={
            str(k).upper(): str(v)
            for k, v in cfg["stale_pricing"]["foreign_calendars"].items()
        },
    )


@dataclass(frozen=True)
class EventStudySettings:
    pre_days: int
    post_days: int
    estimation_days: int
    min_estimation_days: int
    band_sigma: float


@dataclass(frozen=True)
class MeanReversionSettings:
    min_obs: int


@dataclass(frozen=True)
class RobustnessSettings:
    seed: int
    n_placebo: int
    tier2_percentiles: tuple[float, ...]
    winsor_pct: float
    exclude_event: str


@dataclass(frozen=True)
class Settings:
    fixtures_dir: Path
    raw_dir: Path
    processed_dir: Path
    panel_dir: Path
    liquidity: LiquiditySettings
    event_study: EventStudySettings
    mean_reversion: MeanReversionSettings
    robustness: RobustnessSettings


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
    volume_window = int(liq.get("volume_window", 60))
    if rolling_window < 2:
        raise ValueError(f"rolling_window must be >= 2, got {rolling_window}")
    if annualisation_days < 1:
        raise ValueError(
            f"annualisation_days must be >= 1, got {annualisation_days}"
        )
    if volume_window < 2:
        raise ValueError(f"volume_window must be >= 2, got {volume_window}")

    es = cfg["event_study"]
    event_study = EventStudySettings(
        pre_days=int(es["pre_days"]),
        post_days=int(es["post_days"]),
        estimation_days=int(es["estimation_days"]),
        min_estimation_days=int(es["min_estimation_days"]),
        band_sigma=float(es["band_sigma"]),
    )
    if event_study.pre_days < 0 or event_study.post_days < 1:
        raise ValueError("event window must have pre_days >= 0 and post_days >= 1")
    if not 2 <= event_study.min_estimation_days <= event_study.estimation_days:
        raise ValueError(
            "min_estimation_days must be between 2 and estimation_days"
        )
    if event_study.band_sigma <= 0:
        raise ValueError(f"band_sigma must be > 0, got {event_study.band_sigma}")

    mr = cfg["mean_reversion"]
    mean_reversion = MeanReversionSettings(min_obs=int(mr["min_obs"]))
    if mean_reversion.min_obs < 10:
        raise ValueError(
            f"mean_reversion.min_obs must be >= 10, got {mean_reversion.min_obs}"
        )

    rb = cfg["robustness"]
    robustness = RobustnessSettings(
        seed=int(rb["seed"]),
        n_placebo=int(rb["n_placebo"]),
        tier2_percentiles=tuple(float(x) for x in rb["tier2_percentiles"]),
        winsor_pct=float(rb["winsor_pct"]),
        exclude_event=str(rb["exclude_event"]),
    )
    if robustness.n_placebo < 1:
        raise ValueError(f"n_placebo must be >= 1, got {robustness.n_placebo}")
    if not 0 < robustness.winsor_pct < 0.5:
        raise ValueError(
            f"winsor_pct must be in (0, 0.5), got {robustness.winsor_pct}"
        )
    for p in robustness.tier2_percentiles:
        if not 0.5 < p < 1.0:
            raise ValueError(f"tier2 percentile must be in (0.5, 1), got {p}")

    return Settings(
        fixtures_dir=_resolve(paths["fixtures"]),
        raw_dir=_resolve(paths["raw"]),
        processed_dir=_resolve(paths["processed"]),
        panel_dir=_resolve(paths["panel"]),
        liquidity=LiquiditySettings(
            rolling_window=rolling_window,
            annualisation_days=annualisation_days,
            volume_window=volume_window,
        ),
        event_study=event_study,
        mean_reversion=mean_reversion,
        robustness=robustness,
    )
