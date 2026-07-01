"""Rater scorer: deterministic five-dimension rule-based scoring + grading.

score = 30*authority + 25*freshness + 25*relevance + 10*uniqueness + 10*engagement
All sub-scores normalized to 0-1 before weighting; total clamped to [0, 100].
No LLM. Pure function, no IO.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..collector.normalizer import normalize_title
from ..collector.parser import Entry
from ..config import RaterConfig, utc_now


@dataclass(frozen=True)
class ScoredEntry:
    """An Entry plus its computed score and grade."""

    entry: Entry
    raw_score: float
    grade: str
    components: dict[str, float] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class ScoreContext:
    """Context needed to score entries: history for uniqueness, now for freshness."""

    now: datetime
    recent_titles: tuple[str, ...] = ()
    rater: RaterConfig | None = None

    @classmethod
    def build(cls, rater: RaterConfig, recent_titles: list[str] | None = None, now: datetime | None = None) -> "ScoreContext":
        return cls(
            now=now or utc_now(),
            recent_titles=tuple(recent_titles or []),
            rater=rater,
        )


def _word_set(title: str) -> frozenset[str]:
    norm = normalize_title(title)
    if not norm:
        return frozenset()
    return frozenset(re.split(r"\s+", norm)) if norm else frozenset()


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def score_authority(entry: Entry, rater: RaterConfig) -> float:
    """Authority from entry source; raw.raw may carry source authority override."""
    # authority is stored on the source, not entry directly. The runner injects
    # source authority via entry.raw["authority"] for decoupling.
    return max(0.0, min(1.0, float(entry.raw.get("authority", 0.5))))


def score_freshness(entry: Entry, ctx: ScoreContext) -> float:
    """freshness = exp(-delta_hours / half_life). > max_age -> 0."""
    rater = ctx.rater
    half_life = rater.freshness_half_life_hours if rater else 72.0
    max_age = rater.max_age_hours if rater else 168.0
    published = entry.published
    if published is None:
        # No publish time: treat as now (delta=0 -> freshness=1.0) per spec.
        return 1.0
    if published.tzinfo is None:
        from datetime import timezone

        published = published.replace(tzinfo=timezone.utc)
    delta_h = (ctx.now - published).total_seconds() / 3600.0
    if delta_h < 0:
        delta_h = 0.0
    if delta_h > max_age:
        return 0.0
    return math.exp(-delta_h / half_life)


def score_relevance(entry: Entry, rater: RaterConfig) -> float:
    """Keyword relevance: title hits weight 1.0, summary hits 0.4.
    relevance = clamp(sum(weight) / target, 0, 1). No keywords -> 0.5 neutral."""
    if not rater.keywords:
        return 0.5
    title_low = entry.title.lower()
    summary_low = (entry.summary or "").lower()
    total = 0.0
    for word, weight in rater.keywords.items():
        w = word.lower()
        if w in title_low:
            total += weight * 1.0
        if w in summary_low:
            total += weight * 0.4
    # Apply penalty words
    for pword, pweight in (rater.penalty_words or {}).items():
        if pword.lower() in title_low or pword.lower() in summary_low:
            total -= pweight
    target = rater.relevance_target or 3.0
    return max(0.0, min(1.0, total / target))


def score_uniqueness(entry: Entry, ctx: ScoreContext) -> float:
    """uniqueness = 1 - max_jaccard vs recent titles."""
    e_words = _word_set(entry.title)
    if not e_words:
        # No title -> treat as unique
        return 1.0
    max_sim = 0.0
    for t in ctx.recent_titles:
        sim = _jaccard(e_words, _word_set(t))
        if sim > max_sim:
            max_sim = sim
    return max(0.0, 1.0 - max_sim)


def score_engagement(entry: Entry, rater: RaterConfig) -> float:
    """Engagement: normalize points/comments if present, else 0."""
    threshold = rater.engagement_threshold or 200.0
    # Look for engagement values in raw
    for key in ("points", "comments", "slash_comments"):
        if key in entry.raw:
            try:
                v = float(entry.raw[key])
                return min(v / threshold, 1.0)
            except (ValueError, TypeError):
                continue
    return 0.0


def grade_for(score_val: float, rater: RaterConfig) -> str:
    """Map score to grade A/B/C based on thresholds."""
    a_thresh = rater.grade_thresholds.get("A", 75)
    b_thresh = rater.grade_thresholds.get("B", 50)
    if score_val >= a_thresh:
        return "A"
    if score_val >= b_thresh:
        return "B"
    return "C"


def score(entry: Entry, ctx: ScoreContext) -> ScoredEntry:
    """Compute the full five-dimension score and grade for an entry."""
    rater = ctx.rater
    if rater is None:
        # Fallback to defaults
        rater = RaterConfig()

    w = rater.weights
    a = score_authority(entry, rater)
    f = score_freshness(entry, ctx)
    r = score_relevance(entry, rater)
    u = score_uniqueness(entry, ctx)
    e = score_engagement(entry, rater)

    total = (
        w.get("authority", 30) * a
        + w.get("freshness", 25) * f
        + w.get("relevance", 25) * r
        + w.get("uniqueness", 10) * u
        + w.get("engagement", 10) * e
    )
    total = max(0.0, min(100.0, total))
    grade = grade_for(total, rater)
    components = {
        "authority": a,
        "freshness": f,
        "relevance": r,
        "uniqueness": u,
        "engagement": e,
    }
    return ScoredEntry(entry=entry, raw_score=round(total, 2), grade=grade, components=components)


def score_many(entries: list[Entry], ctx: ScoreContext) -> list[ScoredEntry]:
    """Score a batch of entries against a shared context."""
    return [score(e, ctx) for e in entries]
