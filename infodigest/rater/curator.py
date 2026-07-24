"""Curator: quality gate before delivery (no LLM).

Pipeline steps (aligned with openclaw editor.md):
1. Noise filter
2. Require link for S/A grades
3. Temporal history filter (48h / force archive)
4. Sort by final score
5. Daily quota trim (S/A/B)
6. Empty → silent (no push) when allow_empty_digest
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from ..collector.parser import Entry
from ..config import RaterConfig, utc_now
from .event_history import EventHistory, get_daily_push_state
from .scorer import ScoredEntry


@dataclass(frozen=True)
class CurateResult:
    """Curated entries ready to push, plus drop stats."""

    entries: list[Entry]
    dropped: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
    silent: bool = False


def _is_noise(title: str, summary: str, patterns: tuple[str, ...]) -> bool:
    text = f"{title} {summary or ''}"
    for pat in patterns:
        try:
            if re.search(pat, text, re.IGNORECASE):
                return True
        except re.error:
            if pat.lower() in text.lower():
                return True
    return False


def _has_valid_link(link: str) -> bool:
    return bool(link) and (
        link.startswith("http://") or link.startswith("https://")
    )


def _grade_of(entry: Entry) -> str:
    return str(entry.raw.get("grade") or entry.grade or "C")


def _score_of(entry: Entry) -> float:
    try:
        return float(entry.raw.get("raw_score", 0))
    except (TypeError, ValueError):
        return 0.0


def scored_to_entry(se: ScoredEntry) -> Entry:
    """Flatten ScoredEntry into Entry with score metadata in raw."""
    raw = dict(se.entry.raw)
    raw["grade"] = se.grade
    raw["raw_score"] = se.raw_score
    raw["components"] = se.components
    return Entry(
        uid=se.entry.uid,
        source_id=se.entry.source_id,
        title=se.entry.title,
        summary=se.entry.summary,
        link=se.entry.link,
        published=se.entry.published,
        raw=raw,
    )


def curate(
    entries: list[Entry],
    rater: RaterConfig,
    history: EventHistory | None = None,
    daily_state: dict[str, int] | None = None,
    now: datetime | None = None,
) -> CurateResult:
    """Filter, rank, and quota-trim entries for push.

    If nothing survives and allow_empty_digest, returns silent=True with empty list.
    """
    now = now or utc_now()
    reasons: dict[str, int] = {}
    kept: list[Entry] = []

    for entry in entries:
        grade = _grade_of(entry)
        score = _score_of(entry)

        if score < rater.min_push_score and grade not in ("S", "A"):
            reasons["below_min_score"] = reasons.get("below_min_score", 0) + 1
            continue

        if _is_noise(entry.title, entry.summary, rater.noise_patterns):
            reasons["noise"] = reasons.get("noise", 0) + 1
            continue

        if rater.require_link_for_high_grade and grade in ("S", "A"):
            if not _has_valid_link(entry.link):
                reasons["no_link"] = reasons.get("no_link", 0) + 1
                continue

        if history is not None:
            decision = history.should_output(
                entry.title,
                now=now,
                text_for_novelty=f"{entry.title} {entry.summary or ''}",
            )
            if not decision.should_output:
                reasons[decision.reason.split("(")[0].strip()] = (
                    reasons.get(decision.reason.split("(")[0].strip(), 0) + 1
                )
                continue
            if decision.downgraded:
                # Soft downgrade: demote grade one step for quota accounting
                demote = {"S": "A", "A": "B", "B": "C"}.get(grade, grade)
                raw = dict(entry.raw)
                raw["grade"] = demote
                raw["downgraded"] = True
                raw["dedup_reason"] = decision.reason
                entry = Entry(
                    uid=entry.uid,
                    source_id=entry.source_id,
                    title=entry.title,
                    summary=entry.summary,
                    link=entry.link,
                    published=entry.published,
                    raw=raw,
                )

        kept.append(entry)

    # Sort by score desc
    kept.sort(key=lambda e: (-_score_of(e), e.title))

    # Daily quotas
    state = dict(daily_state or {"S": 0, "A": 0, "B": 0})
    quotas = rater.daily_quotas
    quota_kept: list[Entry] = []
    for entry in kept:
        grade = _grade_of(entry)
        if grade == "C":
            reasons["grade_c"] = reasons.get("grade_c", 0) + 1
            continue
        limit = quotas.get(grade)
        if limit is not None and state.get(grade, 0) >= limit:
            reasons[f"quota_{grade}"] = reasons.get(f"quota_{grade}", 0) + 1
            continue
        quota_kept.append(entry)
        if grade in state:
            state[grade] = state.get(grade, 0) + 1

    dropped = len(entries) - len(quota_kept)
    if not quota_kept:
        return CurateResult(
            entries=[],
            dropped=dropped,
            reasons=reasons,
            silent=bool(rater.allow_empty_digest),
        )
    return CurateResult(
        entries=quota_kept, dropped=dropped, reasons=reasons, silent=False
    )


def curate_from_scored(
    scored: list[ScoredEntry],
    rater: RaterConfig,
    history: EventHistory | None = None,
    conn=None,
    now: datetime | None = None,
) -> CurateResult:
    """Convenience: convert ScoredEntry list then curate, loading daily state from conn."""
    now = now or utc_now()
    daily = get_daily_push_state(conn, now) if conn is not None else None
    entries = [scored_to_entry(se) for se in scored]
    return curate(entries, rater, history=history, daily_state=daily, now=now)
