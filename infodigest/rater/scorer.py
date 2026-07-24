"""Rater scorer: deterministic multi-dimension scoring + event tier + interest.

final = clamp(base_score * interest_weight + event_boost - decay + novelty, 0, 100)

base_score = 30*authority + 25*freshness + 25*relevance + 10*uniqueness + 10*engagement
No LLM. Pure function when history adjustments are passed in via ScoreContext.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime

from ..collector.normalizer import normalize_title
from ..collector.parser import Entry
from ..config import InterestsConfig, RaterConfig, utc_now


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
    # Optional per-entry overrides keyed by uid (from EventHistory)
    decay_by_uid: dict[str, float] = field(default_factory=dict)
    novelty_by_uid: dict[str, float] = field(default_factory=dict)
    # Source category/tags for interest weighting: source_id -> (category, tags)
    source_meta: dict[str, tuple[str, tuple[str, ...]]] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        rater: RaterConfig,
        recent_titles: list[str] | None = None,
        now: datetime | None = None,
        decay_by_uid: dict[str, float] | None = None,
        novelty_by_uid: dict[str, float] | None = None,
        source_meta: dict[str, tuple[str, tuple[str, ...]]] | None = None,
    ) -> "ScoreContext":
        return cls(
            now=now or utc_now(),
            recent_titles=tuple(recent_titles or []),
            rater=rater,
            decay_by_uid=dict(decay_by_uid or {}),
            novelty_by_uid=dict(novelty_by_uid or {}),
            source_meta=dict(source_meta or {}),
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
    return max(0.0, min(1.0, float(entry.raw.get("authority", 0.5))))


def score_freshness(entry: Entry, ctx: ScoreContext) -> float:
    """freshness = exp(-delta_hours / half_life). > max_age -> 0."""
    rater = ctx.rater
    half_life = rater.freshness_half_life_hours if rater else 72.0
    max_age = rater.max_age_hours if rater else 168.0
    published = entry.published
    if published is None:
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
    """Keyword relevance: title hits weight 1.0, summary hits 0.4."""
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
    for pword, pweight in (rater.penalty_words or {}).items():
        if pword.lower() in title_low or pword.lower() in summary_low:
            total -= pweight
    target = rater.relevance_target or 3.0
    return max(0.0, min(1.0, total / target))


def score_uniqueness(entry: Entry, ctx: ScoreContext) -> float:
    """uniqueness = 1 - max_jaccard vs recent titles."""
    e_words = _word_set(entry.title)
    if not e_words:
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
    for key in ("points", "comments", "slash_comments"):
        if key in entry.raw:
            try:
                v = float(entry.raw[key])
                return min(v / threshold, 1.0)
            except (ValueError, TypeError):
                continue
    return 0.0


@dataclass(frozen=True)
class EventTierResult:
    tier: str  # S / A / B / C
    boost: float
    reason: str
    matched: tuple[str, ...] = ()


def _keyword_hit(keyword: str, text: str) -> bool:
    """Case-insensitive keyword match. Short ASCII tokens use word boundaries
    to avoid false positives (e.g. RCE matching inside 'source')."""
    kw = keyword.lower()
    # CJK or multi-word / special tokens: substring is fine
    if any(ord(c) > 127 for c in keyword) or " " in keyword or "-" in keyword:
        return kw in text
    # Short pure-alnum tokens: require word boundary
    if len(kw) <= 4 and kw.isalnum():
        return re.search(rf"\b{re.escape(kw)}\b", text) is not None
    return kw in text


def score_event_tier(title: str, summary: str, rater: RaterConfig) -> EventTierResult:
    """Match event_patterns keywords; return tier + boost. No match → C / 0."""
    text = f"{title} {summary or ''}".lower()
    tiers = rater.event_tiers

    for kw in tiers.s_keywords:
        if _keyword_hit(kw, text):
            return EventTierResult("S", tiers.s_boost, f"S:{kw}", (kw,))
    for kw in tiers.a_keywords:
        if _keyword_hit(kw, text):
            return EventTierResult("A", tiers.a_boost, f"A:{kw}", (kw,))
    for kw in tiers.b_keywords:
        if _keyword_hit(kw, text):
            return EventTierResult("B", tiers.b_boost, f"B:{kw}", (kw,))
    return EventTierResult("C", 0.0, "no_event_pattern", ())


def score_interest(
    entry: Entry,
    interests: InterestsConfig,
    source_meta: dict[str, tuple[str, tuple[str, ...]]] | None = None,
) -> float:
    """Interest weight from category/tags. Max matching weight, else default."""
    meta = (source_meta or {}).get(entry.source_id)
    # Also allow category/tags injected on entry.raw
    category = entry.raw.get("category", "")
    tags: tuple[str, ...] = tuple(entry.raw.get("tags") or ())
    if meta:
        category = category or meta[0]
        tags = tags or meta[1]

    candidates: list[float] = []
    if category and category in interests.weights:
        candidates.append(interests.weights[category])
    for tag in tags:
        if tag in interests.weights:
            candidates.append(interests.weights[tag])
    if candidates:
        return max(0.0, min(1.5, max(candidates)))
    return max(0.0, min(1.5, interests.default_weight))


def grade_for(score_val: float, rater: RaterConfig) -> str:
    """Map score to grade S/A/B/C based on thresholds."""
    s_thresh = rater.grade_thresholds.get("S", 90)
    a_thresh = rater.grade_thresholds.get("A", 75)
    b_thresh = rater.grade_thresholds.get("B", 50)
    if score_val >= s_thresh:
        return "S"
    if score_val >= a_thresh:
        return "A"
    if score_val >= b_thresh:
        return "B"
    return "C"


def score_base(entry: Entry, ctx: ScoreContext) -> tuple[float, dict[str, float]]:
    """Compute five-dimension base score (0-100) and component dict."""
    rater = ctx.rater or RaterConfig()
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
    return total, {
        "authority": a,
        "freshness": f,
        "relevance": r,
        "uniqueness": u,
        "engagement": e,
    }


def score(entry: Entry, ctx: ScoreContext) -> ScoredEntry:
    """Compute full score: base * interest + event_boost - decay + novelty."""
    rater = ctx.rater
    if rater is None:
        rater = RaterConfig()

    base, comps = score_base(entry, ctx)
    interest = score_interest(entry, rater.interests, ctx.source_meta)
    tier = score_event_tier(entry.title, entry.summary, rater)
    decay = float(ctx.decay_by_uid.get(entry.uid, 0.0))
    novelty = float(ctx.novelty_by_uid.get(entry.uid, 0.0))

    final = base * interest + tier.boost - decay + novelty
    final = max(0.0, min(100.0, final))
    grade = grade_for(final, rater)

    components = {
        **comps,
        "base": round(base, 2),
        "interest": interest,
        "event_boost": tier.boost,
        "event_tier": {"S": 1.0, "A": 0.8, "B": 0.5, "C": 0.2}.get(tier.tier, 0.2),
        "decay": decay,
        "novelty": novelty,
        "final": round(final, 2),
    }
    # Attach display metadata into a copy of entry.raw for downstream templates
    new_raw = dict(entry.raw)
    new_raw["grade"] = grade
    new_raw["raw_score"] = round(final, 2)
    new_raw["event_tier"] = tier.tier
    new_raw["event_reason"] = tier.reason
    new_raw["interest"] = interest
    annotated = Entry(
        uid=entry.uid,
        source_id=entry.source_id,
        title=entry.title,
        summary=entry.summary,
        link=entry.link,
        published=entry.published,
        raw=new_raw,
    )
    return ScoredEntry(
        entry=annotated,
        raw_score=round(final, 2),
        grade=grade,
        components=components,
    )


def score_many(entries: list[Entry], ctx: ScoreContext) -> list[ScoredEntry]:
    """Score a batch of entries against a shared context."""
    return [score(e, ctx) for e in entries]
