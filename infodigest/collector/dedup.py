"""Collector dedup: sha1 primary key + SequenceMatcher/Jaccard fuzzy dedup.

Two-stage:
1. Primary key dedup: identical uid (sha1(norm_title + domain)) dropped.
2. Fuzzy dedup: max(SequenceMatcher, Jaccard) on titles > threshold dropped,
   keeping the earliest published (or first-seen) entry.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .normalizer import normalize_title
from .parser import Entry

_WS_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w\u4e00-\u9fff]", re.UNICODE)


def _word_set(title: str) -> frozenset[str]:
    """Tokenize a normalized title into a word set."""
    norm = normalize_title(title)
    if not norm:
        return frozenset()
    return frozenset(_WS_RE.split(norm))


def _compact_title(title: str) -> str:
    """Normalize title for SequenceMatcher (CJK-friendly, strip punctuation)."""
    norm = normalize_title(title)
    return _NON_WORD_RE.sub("", norm).lower()


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity between two word sets. 0 if both empty."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def sequence_ratio(a: str, b: str) -> float:
    """SequenceMatcher ratio on compact titles."""
    ca, cb = _compact_title(a), _compact_title(b)
    if not ca and not cb:
        return 0.0
    if not ca or not cb:
        return 0.0
    return SequenceMatcher(None, ca, cb).ratio()


def title_similarity(a: str, b: str) -> float:
    """Combined similarity: max(SequenceMatcher, Jaccard). Better for CJK short titles."""
    seq = sequence_ratio(a, b)
    jac = jaccard(_word_set(a), _word_set(b))
    return max(seq, jac)


def dedup_entries(
    entries: list[Entry],
    recent_titles: list[str] | None = None,
    similarity_threshold: float = 0.75,
) -> tuple[list[Entry], int]:
    """Deduplicate entries.

    Returns (kept, num_dropped). Drops:
    - exact uid duplicates (primary key)
    - entries whose title similarity > threshold vs an earlier kept entry
      (within this batch and vs recent_titles history)

    recent_titles: titles from the last N days for cross-batch fuzzy dedup.
    """
    seen_uids: set[str] = set()
    kept: list[Entry] = []
    dropped = 0
    history = [t for t in (recent_titles or []) if t]

    for entry in entries:
        # Stage 1: primary key
        if entry.uid in seen_uids:
            dropped += 1
            continue
        seen_uids.add(entry.uid)

        # Stage 2: fuzzy vs kept in this batch + recent history
        is_dup = False
        for prev in kept:
            if title_similarity(entry.title, prev.title) >= similarity_threshold:
                is_dup = True
                break
        if not is_dup:
            for ht in history:
                if title_similarity(entry.title, ht) >= similarity_threshold:
                    is_dup = True
                    break

        if is_dup:
            dropped += 1
            continue

        kept.append(entry)

    return kept, dropped


def dedup_cross_source(
    entries: list[Entry],
    similarity_threshold: float = 0.75,
) -> tuple[list[Entry], int]:
    """Cross-source dedup: when two entries from different sources have
    near-identical titles, keep only the one with higher source authority
    (entry.raw['authority']). If equal, keep first-seen.

    Returns (kept, num_dropped). Operates on title similarity only.
    """
    # Sort by authority desc so highest-authority version is seen first
    sortable = sorted(entries, key=lambda e: -float(e.raw.get("authority", 0.5)))
    seen_uids: set[str] = set()
    kept: list[Entry] = []
    dropped = 0
    for entry in sortable:
        if entry.uid in seen_uids:
            dropped += 1
            continue
        seen_uids.add(entry.uid)
        is_dup = False
        for prev in kept:
            if title_similarity(entry.title, prev.title) >= similarity_threshold:
                is_dup = True
                break
        if is_dup:
            dropped += 1
            continue
        kept.append(entry)
    return kept, dropped
