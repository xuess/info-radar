"""Offline regression fixture for scoring: 5 fixed entries with expected
score ranges and grades. Guards against silent weight/threshold drift.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from infodigest.collector.parser import Entry

# Fixed reference time for regression
REGRESSION_NOW = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)


def _e(uid, title, summary, published, authority, raw=None):
    r = {"authority": authority}
    if raw:
        r.update(raw)
    return Entry(
        uid=uid, source_id="reg", title=title, summary=summary,
        link=f"https://example.com/{uid}", published=published, raw=r,
    )


REGRESSION_ENTRIES = [
    # 1. Fresh, high authority, keyword-rich, unique, high engagement -> A
    _e("reg1", "AI LLM agent framework released", "New agent framework for LLM reasoning",
       REGRESSION_NOW, 0.95, raw={"points": 300}),
    # 2. Fresh, medium authority, some keywords, unique, no engagement -> B/A boundary
    _e("reg2", "Rust security advisory patched", "Critical vulnerability fixed in rust crate",
       REGRESSION_NOW - timedelta(hours=6), 0.8),
    # 3. Stale (4 days), medium authority, few keywords -> B/C
    _e("reg3", "Open source weekly roundup", "Highlights from opensource community",
       REGRESSION_NOW - timedelta(hours=96), 0.6),
    # 4. Very old (>7 days) -> freshness 0 -> C
    _e("reg4", "Old AI news from last month", "AI was big last month too",
       REGRESSION_NOW - timedelta(hours=240), 0.7),
    # 5. Low authority, no keywords, unique -> low score C
    _e("reg5", "Random community discussion", "Just people chatting about stuff",
       REGRESSION_NOW - timedelta(hours=3), 0.3),
]

# Expected (grade, min_score, max_score) per entry — stable across runs
EXPECTED = [
    ("A", 75, 100),
    ("B", 50, 85),
    ("C", 0, 75),  # stale -> freshness low
    ("C", 0, 55),  # very old -> freshness 0
    ("C", 0, 45),  # low authority, no keywords
]
