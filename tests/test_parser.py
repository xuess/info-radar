"""Tests for collector/parser.py"""
from __future__ import annotations

from pathlib import Path

from infodigest.collector.parser import Entry, parse
from infodigest.config import Source

TEST_SOURCE = Source(id="test", url="https://example.com/feed", category="tech", authority=0.8, lang="en")


class TestParseRss2:
    def test_parses_rss2_items(self, rss2_bytes):
        entries = parse(rss2_bytes, TEST_SOURCE)
        # 4 items in fixture, all have links
        assert len(entries) == 4
        assert all(isinstance(e, Entry) for e in entries)

    def test_titles_extracted(self, rss2_bytes):
        entries = parse(rss2_bytes, TEST_SOURCE)
        titles = [e.title for e in entries]
        assert "AI breakthrough: new reasoning model" in titles
        assert "Open source weekly digest" in titles

    def test_summary_strips_html(self, rss2_bytes):
        entries = parse(rss2_bytes, TEST_SOURCE)
        ai = next(e for e in entries if "AI breakthrough" in e.title)
        assert "<" not in ai.summary
        assert "reasoning model" in ai.summary

    def test_published_parsed(self, rss2_bytes):
        entries = parse(rss2_bytes, TEST_SOURCE)
        ai = next(e for e in entries if "AI breakthrough" in e.title)
        assert ai.published is not None
        assert ai.published.year == 2026
        assert ai.published.month == 7

    def test_missing_published_is_none(self, rss2_bytes):
        entries = parse(rss2_bytes, TEST_SOURCE)
        no_date = next(e for e in entries if "No date" in e.title)
        assert no_date.published is None

    def test_uid_is_sha1_hex(self, rss2_bytes):
        entries = parse(rss2_bytes, TEST_SOURCE)
        for e in entries:
            assert len(e.uid) == 40
            assert all(c in "0123456789abcdef" for c in e.uid)

    def test_uid_stable_for_same_title(self, rss2_bytes):
        entries = parse(rss2_bytes, TEST_SOURCE)
        ai = next(e for e in entries if "AI breakthrough" in e.title)
        # Reparse, uid should be identical
        entries2 = parse(rss2_bytes, TEST_SOURCE)
        ai2 = next(e for e in entries2 if "AI breakthrough" in e.title)
        assert ai.uid == ai2.uid

    def test_link_preserved(self, rss2_bytes):
        entries = parse(rss2_bytes, TEST_SOURCE)
        ai = next(e for e in entries if "AI breakthrough" in e.title)
        assert ai.link == "https://example.com/blog/ai-breakthrough"


class TestParseAtom:
    def test_parses_atom_entries(self, atom_bytes):
        entries = parse(atom_bytes, TEST_SOURCE)
        # 3 entries, but one has no link -> 2 kept
        assert len(entries) == 2

    def test_skips_no_link_entry(self, atom_bytes):
        entries = parse(atom_bytes, TEST_SOURCE)
        titles = [e.title for e in entries]
        assert not any("no link" in t for t in titles)

    def test_content_fallback_for_summary(self, atom_bytes):
        entries = parse(atom_bytes, TEST_SOURCE)
        rust = next(e for e in entries if "Rust" in e.title)
        # content had script + p; script removed
        assert "alert" not in rust.summary
        assert "vulnerability" in rust.summary

    def test_atom_published(self, atom_bytes):
        entries = parse(atom_bytes, TEST_SOURCE)
        llm = next(e for e in entries if "LLM" in e.title)
        assert llm.published is not None
        assert llm.published.year == 2026


class TestParseBadFeed:
    def test_bad_feed_returns_empty(self, bad_feed_bytes):
        entries = parse(bad_feed_bytes, TEST_SOURCE)
        assert entries == []

    def test_empty_content_returns_empty(self):
        assert parse(b"", TEST_SOURCE) == []
        assert parse("", TEST_SOURCE) == []


class TestParseSourceDomain:
    def test_uid_includes_source_domain(self, rss2_bytes):
        s1 = Source(id="a", url="https://a.com/feed")
        s2 = Source(id="b", url="https://b.com/feed")
        e1 = parse(rss2_bytes, s1)
        e2 = parse(rss2_bytes, s2)
        # Same title but different domain -> different uid
        ai1 = next(e for e in e1 if "AI breakthrough" in e.title)
        ai2 = next(e for e in e2 if "AI breakthrough" in e.title)
        assert ai1.uid != ai2.uid
