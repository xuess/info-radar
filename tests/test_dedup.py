"""Tests for collector/dedup.py"""
from __future__ import annotations

from datetime import datetime, timezone

from infodigest.collector.dedup import _word_set, dedup_entries, jaccard
from infodigest.collector.parser import Entry


def _entry(uid: str, title: str, source_id: str = "test") -> Entry:
    return Entry(
        uid=uid,
        source_id=source_id,
        title=title,
        summary="",
        link=f"https://example.com/{uid}",
        published=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


class TestJaccard:
    def test_identical_sets(self):
        a = _word_set("hello world")
        assert jaccard(a, a) == 1.0

    def test_disjoint_sets(self):
        a = _word_set("hello world")
        b = _word_set("foo bar")
        assert jaccard(a, b) == 0.0

    def test_partial_overlap(self):
        a = _word_set("hello world foo")
        b = _word_set("hello bar baz")
        # intersection: hello =1; union: hello,world,foo,bar,baz =5
        assert jaccard(a, b) == 1 / 5

    def test_both_empty(self):
        assert jaccard(frozenset(), frozenset()) == 0.0


class TestDedupEntries:
    def test_exact_uid_dedup(self):
        entries = [_entry("u1", "AI breakthrough"), _entry("u1", "AI breakthrough")]
        kept, dropped = dedup_entries(entries)
        assert len(kept) == 1
        assert dropped == 1

    def test_no_duplicates_kept_all(self):
        entries = [
            _entry("u1", "AI breakthrough"),
            _entry("u2", "Rust security advisory"),
            _entry("u3", "Open source weekly"),
        ]
        kept, dropped = dedup_entries(entries)
        assert len(kept) == 3
        assert dropped == 0

    def test_fuzzy_title_dedup(self):
        # Near-identical titles differing by one word -> high Jaccard
        entries = [
            _entry("u1", "AI breakthrough model released"),
            _entry("u2", "AI breakthrough model release"),
        ]
        kept, dropped = dedup_entries(entries, similarity_threshold=0.8)
        # {ai,breakthrough,model,released} vs {ai,breakthrough,model,release}
        # intersection 3, union 5 = 0.6 < 0.8 -> NOT deduped
        assert len(kept) == 2
        assert dropped == 0

    def test_fuzzy_title_dedup_high_similarity(self):
        # Identical except trailing punctuation -> Jaccard 1.0
        entries = [
            _entry("u1", "AI breakthrough model released!"),
            _entry("u2", "AI breakthrough model released"),
        ]
        kept, dropped = dedup_entries(entries, similarity_threshold=0.8)
        assert len(kept) == 1
        assert dropped == 1

    def test_fuzzy_below_threshold_kept(self):
        entries = [
            _entry("u1", "AI breakthrough announced today"),
            _entry("u2", "Rust security advisory critical"),
        ]
        kept, dropped = dedup_entries(entries, similarity_threshold=0.8)
        assert len(kept) == 2
        assert dropped == 0

    def test_empty_input(self):
        kept, dropped = dedup_entries([])
        assert kept == []
        assert dropped == 0

    def test_recent_titles_fuzzy_dedup(self):
        entries = [_entry("u1", "AI breakthrough announced today")]
        recent = ["AI breakthrough announced today!"]  # Jaccard 1.0 after normalize
        kept, dropped = dedup_entries(entries, recent_titles=recent, similarity_threshold=0.8)
        assert len(kept) == 0
        assert dropped == 1

    def test_recent_titles_below_threshold(self):
        entries = [_entry("u1", "AI breakthrough announced today")]
        recent = ["Rust security advisory"]
        kept, dropped = dedup_entries(entries, recent_titles=recent, similarity_threshold=0.8)
        assert len(kept) == 1
        assert dropped == 0

    def test_idempotent_on_same_input(self):
        entries = [
            _entry("u1", "AI breakthrough"),
            _entry("u2", "Rust security"),
        ]
        kept1, _ = dedup_entries(entries)
        kept2, _ = dedup_entries(kept1)
        assert {e.uid for e in kept1} == {e.uid for e in kept2}
