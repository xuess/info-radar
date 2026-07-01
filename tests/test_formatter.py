"""Tests for formatter/builder.py — Jinja2 rendering + segmentation."""
from __future__ import annotations

import json
from datetime import datetime, timezone


from infodigest.collector.parser import Entry
from infodigest.config import CONFIG_DIR, DeliveryConfig
from infodigest.formatter.builder import (
    render_dingtalk,
    render_feishu,
    segment_entries,
    validate_feishu_json,
)

TEMPLATES = CONFIG_DIR / "templates"


def _entry(uid, title="Test", summary="A summary", grade="B", source_id="test") -> Entry:
    return Entry(
        uid=uid, source_id=source_id, title=title, summary=summary,
        link=f"https://example.com/{uid}", published=datetime(2026, 7, 2, tzinfo=timezone.utc),
        raw={"authority": 0.8, "grade": grade},
    )


def _scored_entry(uid, title="Test", summary="A summary", grade="B"):
    """A lightweight scored-entry-like object with .grade attribute."""
    e = _entry(uid, title, summary)
    # builder only reads .grade, .title, .summary, .link, .source_id
    # Entry doesn't have .grade; the runner wraps in ScoredEntry. For template
    # tests we attach grade via a simple wrapper.
    class _S:
        def __init__(self, e, g):
            self.uid = e.uid
            self.source_id = e.source_id
            self.title = e.title
            self.summary = e.summary
            self.link = e.link
            self.published = e.published
            self.raw = e.raw
            self.grade = g

    return _S(e, grade)


class TestSegmentEntries:
    def test_single_batch_under_limits(self):
        entries = [_entry(f"u{i}", f"Title {i}") for i in range(5)]
        batches = segment_entries(entries, max_entries=20, max_bytes=30000)
        assert len(batches) == 1
        assert len(batches[0]) == 5

    def test_splits_by_entry_count(self):
        entries = [_entry(f"u{i}", f"Title {i}") for i in range(25)]
        batches = segment_entries(entries, max_entries=10, max_bytes=30000)
        assert len(batches) == 3
        assert len(batches[0]) == 10
        assert len(batches[1]) == 10
        assert len(batches[2]) == 5

    def test_splits_by_byte_size(self):
        # Large summaries force byte-size split
        entries = [_entry(f"u{i}", f"Title {i}", summary="x" * 5000) for i in range(10)]
        batches = segment_entries(entries, max_entries=20, max_bytes=10000)
        assert len(batches) > 1
        for batch in batches:
            assert len(batch) <= 20

    def test_empty_entries(self):
        assert segment_entries([], max_entries=20, max_bytes=30000) == []

    def test_single_entry_too_large_still_in_batch(self):
        # One enormous entry — must still go in its own batch (not dropped)
        entries = [_entry("u1", "Huge", summary="x" * 50000)]
        batches = segment_entries(entries, max_entries=20, max_bytes=30000)
        assert len(batches) == 1
        assert len(batches[0]) == 1


class TestRenderDingtalk:
    def test_renders_markdown(self):
        entries = [_scored_entry("u1", "AI news", "Great summary", "A")]
        msgs = render_dingtalk(entries, sources=["hn"], templates_dir=TEMPLATES)
        assert len(msgs) == 1
        assert "AI news" in msgs[0].content
        assert "https://example.com/u1" in msgs[0].content
        assert "InfoDigest" in msgs[0].content

    def test_contains_grade_marker(self):
        entries = [_scored_entry("u1", "AI news", grade="A")]
        msgs = render_dingtalk(entries, templates_dir=TEMPLATES)
        assert "A 级推荐" in msgs[0].content
        assert "🔥" in msgs[0].content

    def test_segmentation_produces_multiple_messages(self):
        entries = [_scored_entry(f"u{i}", f"Title {i}", "x" * 5000) for i in range(10)]
        msgs = render_dingtalk(entries, templates_dir=TEMPLATES, delivery=DeliveryConfig(max_entries_per_message=3, max_message_bytes=30000))
        assert len(msgs) > 1
        assert sum(m.entry_count for m in msgs) == 10

    def test_empty_entries(self):
        msgs = render_dingtalk([], templates_dir=TEMPLATES)
        # Even with no entries, produces one message with header
        assert len(msgs) == 1
        assert "InfoDigest" in msgs[0].content


class TestRenderFeishu:
    def test_renders_valid_json(self):
        entries = [_scored_entry("u1", "AI news", "Great summary", "A")]
        msgs = render_feishu(entries, sources=["hn"], templates_dir=TEMPLATES)
        assert len(msgs) == 1
        assert validate_feishu_json(msgs[0].content)
        data = json.loads(msgs[0].content)
        assert data["msg_type"] == "interactive"
        assert "card" in data

    def test_json_contains_entries(self):
        entries = [
            _scored_entry("u1", "First post", "Summary one", "A"),
            _scored_entry("u2", "Second post", "Summary two", "B"),
        ]
        msgs = render_feishu(entries, templates_dir=TEMPLATES)
        content = msgs[0].content
        assert "First post" in content
        assert "Second post" in content

    def test_segmentation(self):
        entries = [_scored_entry(f"u{i}", f"Title {i}", "x" * 5000) for i in range(10)]
        msgs = render_feishu(entries, templates_dir=TEMPLATES, delivery=DeliveryConfig(max_entries_per_message=3, max_message_bytes=30000))
        assert len(msgs) > 1
        for m in msgs:
            assert validate_feishu_json(m.content), f"batch {m.batch_index} not valid JSON"

    def test_empty_entries_valid_json(self):
        msgs = render_feishu([], templates_dir=TEMPLATES)
        assert len(msgs) == 1
        assert validate_feishu_json(msgs[0].content)


class TestValidateFeishuJson:
    def test_valid_json(self):
        assert validate_feishu_json('{"a": 1}')

    def test_invalid_json(self):
        assert not validate_feishu_json("not json {")

    def test_trailing_comma_cleaned(self):
        # The _clean_json helper should remove trailing commas
        assert validate_feishu_json('{"a": 1, "b": 2,}')
