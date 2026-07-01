"""Configuration loading: dataclasses + YAML for all tunable params.

All tunable parameters live in config/*.yaml. Code loads them here; no scattered
hardcoding of thresholds, weights, or secrets.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


@dataclass(frozen=True)
class Source:
    """A single RSS source from feeds.yaml."""

    id: str
    url: str
    category: str = ""
    authority: float = 0.5
    lang: str = ""
    tags: tuple[str, ...] = ()
    enabled: bool = True

    @property
    def domain(self) -> str:
        """Source domain extracted from url, used in dedup key."""
        from urllib.parse import urlparse

        host = urlparse(self.url).hostname or ""
        return host.lower().removeprefix("www.")


@dataclass(frozen=True)
class CollectConfig:
    timeout: float = 15.0
    max_retries: int = 3
    user_agent: str = "InfoDigest/1.0"
    respect_robots: bool = True


@dataclass(frozen=True)
class DeliveryConfig:
    feishu_enabled: bool = True
    dingtalk_enabled: bool = True
    feishu_rate_per_min: int = 5
    dingtalk_rate_per_min: int = 20
    max_entries_per_message: int = 20
    max_message_bytes: int = 30000
    push_grade_min: str = "B"
    retry_max: int = 3


@dataclass(frozen=True)
class StorageConfig:
    db_path: str = "data/infodigest.db"
    failed_digests_dir: str = "data/failed_digests"


@dataclass(frozen=True)
class ScheduleConfig:
    cron: str = "0 1,9 * * *"


@dataclass(frozen=True)
class RaterConfig:
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "authority": 30,
            "freshness": 25,
            "relevance": 25,
            "uniqueness": 10,
            "engagement": 10,
        }
    )
    freshness_half_life_hours: float = 72.0
    max_age_hours: float = 168.0
    relevance_target: float = 3.0
    engagement_threshold: float = 200.0
    grade_thresholds: dict[str, float] = field(
        default_factory=lambda: {"A": 75, "B": 50}
    )
    push_grade_min: str = "B"
    keywords: dict[str, float] = field(default_factory=dict)
    penalty_words: dict[str, float] = field(default_factory=dict)
    dedup_similarity: float = 0.8
    dedup_window_days: int = 7


@dataclass(frozen=True)
class Config:
    sources: tuple[Source, ...] = ()
    collect: CollectConfig = field(default_factory=CollectConfig)
    delivery: DeliveryConfig = field(default_factory=DeliveryConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    rater: RaterConfig = field(default_factory=RaterConfig)
    config_dir: Path = CONFIG_DIR

    @property
    def enabled_sources(self) -> tuple[Source, ...]:
        return tuple(s for s in self.sources if s.enabled)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def _build_source(raw: dict[str, Any]) -> Source:
    tags = raw.get("tags") or []
    return Source(
        id=raw["id"],
        url=raw["url"],
        category=raw.get("category", ""),
        authority=float(raw.get("authority", 0.5)),
        lang=raw.get("lang", ""),
        tags=tuple(tags),
        enabled=bool(raw.get("enabled", True)),
    )


def load_config(config_dir: Path | None = None) -> Config:
    """Load full configuration from config_dir (default repo config/)."""
    cdir = config_dir or CONFIG_DIR
    settings = _load_yaml(cdir / "settings.yaml")
    feeds = _load_yaml(cdir / "feeds.yaml")
    rater_raw = _load_yaml(cdir / "rater.yaml")

    sources = tuple(_build_source(s) for s in (feeds.get("sources") or []))

    storage_raw = settings.get("storage") or {}
    db_path = storage_raw.get("db_path", "data/infodigest.db")
    # Make db_path absolute relative to repo root for consistent access.
    if not os.path.isabs(db_path):
        db_path = str(REPO_ROOT / db_path)

    collect_raw = settings.get("collect") or {}
    delivery_raw = settings.get("delivery") or {}
    schedule_raw = settings.get("schedule") or {}

    return Config(
        sources=sources,
        collect=CollectConfig(
            timeout=float(collect_raw.get("timeout", 15.0)),
            max_retries=int(collect_raw.get("max_retries", 3)),
            user_agent=collect_raw.get(
                "user_agent", "InfoDigest/1.0"
            ),
            respect_robots=bool(collect_raw.get("respect_robots", True)),
        ),
        delivery=DeliveryConfig(
            feishu_enabled=bool(delivery_raw.get("feishu_enabled", True)),
            dingtalk_enabled=bool(delivery_raw.get("dingtalk_enabled", True)),
            feishu_rate_per_min=int(delivery_raw.get("feishu_rate_per_min", 5)),
            dingtalk_rate_per_min=int(
                delivery_raw.get("dingtalk_rate_per_min", 20)
            ),
            max_entries_per_message=int(
                delivery_raw.get("max_entries_per_message", 20)
            ),
            max_message_bytes=int(delivery_raw.get("max_message_bytes", 30000)),
            push_grade_min=delivery_raw.get("push_grade_min", "B"),
            retry_max=int(delivery_raw.get("retry_max", 3)),
        ),
        storage=StorageConfig(
            db_path=db_path,
            failed_digests_dir=storage_raw.get(
                "failed_digests_dir", "data/failed_digests"
            ),
        ),
        schedule=ScheduleConfig(
            cron=schedule_raw.get("cron", "0 1,9 * * *")
        ),
        rater=RaterConfig(
            weights=dict(rater_raw.get("weights") or {}),
            freshness_half_life_hours=float(
                rater_raw.get("freshness_half_life_hours", 72.0)
            ),
            max_age_hours=float(rater_raw.get("max_age_hours", 168.0)),
            relevance_target=float(rater_raw.get("relevance_target", 3.0)),
            engagement_threshold=float(
                rater_raw.get("engagement_threshold", 200.0)
            ),
            grade_thresholds=dict(rater_raw.get("grade_thresholds") or {"A": 75, "B": 50}),
            push_grade_min=rater_raw.get("push_grade_min", "B"),
            keywords=dict(rater_raw.get("keywords") or {}),
            penalty_words=dict(rater_raw.get("penalty_words") or {}),
            dedup_similarity=float(rater_raw.get("dedup_similarity", 0.8)),
            dedup_window_days=int(rater_raw.get("dedup_window_days", 7)),
        ),
        config_dir=cdir,
    )


def utc_now() -> datetime:
    """UTC now, tz-aware. Centralized for testability."""
    return datetime.now(timezone.utc)
