"""Collector dedup: sha1 primary key + title Jaccard similarity dedup.

Two-stage:
1. Primary key dedup: identical uid (sha1(norm_title + domain)) dropped.
2. Fuzzy dedup: Jaccard similarity on title word-sets > threshold dropped,
   keeping the earliest published (or first-seen) entry.
"""
from __future__ import annotations

import re

from .normalizer import normalize_title
from .parser import Entry

_WS_RE = re.compile(r"\s+")


def _word_set(title: str) -> frozenset[str]:
    """Tokenize a normalized title into a word set."""
    norm = normalize_title(title)
    if not norm:
        return frozenset()
    return frozenset(_WS_RE.split(norm))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity between two word sets. 0 if both empty."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def dedup_entries(
    entries: list[Entry],
    recent_titles: list[str] | None = None,
    similarity_threshold: float = 0.8,
) -> tuple[list[Entry], int]:
    """Deduplicate entries.

    Returns (kept, num_dropped). Drops:
    - exact uid duplicates (primary key)
    - entries whose title Jaccard > threshold vs an earlier kept entry
      (within this batch and vs recent_titles history)

    recent_titles: titles from the last N days for cross-batch fuzzy dedup.
    """
    seen_uids: set[str] = set()
    kept: list[Entry] = []
    dropped = 0

    # Pre-compute word sets for recent history for fuzzy comparison
    history_sets: list[frozenset[str]] = []
    if recent_titles:
        history_sets = [_word_set(t) for t in recent_titles if t]

    for entry in entries:
        # Stage 1: primary key
        if entry.uid in seen_uids:
            dropped += 1
            continue
        seen_uids.add(entry.uid)

        # Stage 2: fuzzy vs kept in this batch + recent history
        e_words = _word_set(entry.title)
        is_dup = False
        for prev in kept:
            if jaccard(e_words, _word_set(prev.title)) >= similarity_threshold:
                is_dup = True
                break
        if not is_dup:
            for hs in history_sets:
                if jaccard(e_words, hs) >= similarity_threshold:
                    is_dup = True
                    break

        if is_dup:
            dropped += 1
            continue

        kept.append(entry)

    return kept, dropped



def dedup_cross_source(
    entries: list[Entry],
    similarity_threshold: float = 0.8,
) -> tuple[list[Entry], int]:
    """Cross-source dedup: when two entries from different sources have
    near-identical titles (Jaccard >= threshold), keep only the one with
    higher source authority (entry.raw['authority']). If equal, keep first-seen.

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
        e_words = _word_set(entry.title)
        is_dup = False
        for prev in kept:
            if jaccard(e_words, _word_set(prev.title)) >= similarity_threshold:
                is_dup = True
                break
        if is_dup:
            dropped += 1
            continue
        kept.append(entry)
    return kept, dropped