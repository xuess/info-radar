"""Tests for formatter/builder.py — Jinja2 rendering + segmentation."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from infodigest.collector.parser import Entry
from infodigest.config import CONFIG_DIR, DeliveryConfig
from infodigest.formatter.builder import (
    render_dingtalk,
    render_feishu,
    render_weekly,
    segment_entries,
    validate_feishu_json,
)

TEMPLATES = CONFIG_DIR / "templates"


def _entry(uid, title="Test", summary="A summary", grade="B", source_id="test"):
    return Entry(
        uid=uid,
        source_id=source_id,
        title=title,
        summary=summary,
        link=f"https://example.com/{uid}",
        published=datetime(2026, 7, 2, tzinfo=timezone.utc),
        raw={"authority": 0.8, "grade": grade},
    )


def _scored_entry(uid, title="Test", summary="A summary", grade="B"):
    e = _entry(uid, title, summary)

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
        assert len(segment_entries([_entry(f"u{i}") for i in range(5)])) == 1

    def test_splits_by_count(self):
        assert len(segment_entries([_entry(f"u{i}") for i in range(25)], max_entries=10)) == 3

    def test_splits_by_bytes(self):
        entries = [_entry(f"u{i}", summary="x" * 5000) for i in range(10)]
        assert len(segment_entries(entries, max_bytes=10000)) > 1

    def test_empty(self):
        assert segment_entries([]) == []


class TestRenderFeishu:
    def test_valid_json(self):
        msgs = render_feishu([_scored_entry("u1", "AI news", "desc", "A")], sources=["hn"])
        assert validate_feishu_json(msgs[0].content)
        d = json.loads(msgs[0].content)
        assert d["msg_type"] == "interactive"

    def test_contains_entries(self):
        msgs = render_feishu([_scored_entry("u1", "First"), _scored_entry("u2", "Second")])
        assert "First" in msgs[0].content and "Second" in msgs[0].content

    def test_segmentation(self):
        entries = [_scored_entry(f"u{i}", summary="x" * 5000) for i in range(10)]
        msgs = render_feishu(entries, delivery=DeliveryConfig(max_entries_per_message=3))
        for m in msgs:
            assert validate_feishu_json(m.content)

    def test_empty(self):
        assert validate_feishu_json(render_feishu([])[0].content)

    def test_special_chars_in_title(self):
        msgs = render_feishu([_scored_entry("u1", 'Title with "quotes" and\nnewlines')])
        assert validate_feishu_json(msgs[0].content)
        assert "quotes" in msgs[0].content

    def test_grade_sections(self):
        msgs = render_feishu([
            _scored_entry("u1", "A item", grade="A"),
            _scored_entry("u2", "B item", grade="B"),
        ])
        d = json.loads(msgs[0].content)
        tags = [e["tag"] for e in d["card"]["elements"] if "tag" in e]
        assert "note" in tags
        assert "div" in tags


class TestRenderDingtalk:
    def test_renders_markdown(self):
        msgs = render_dingtalk([_scored_entry("u1", "AI news", "desc", "A")], sources=["hn"])
        assert "AI news" in msgs[0].content
        assert "信息雷达" in msgs[0].content

    def test_grade_marker(self):
        msgs = render_dingtalk([_scored_entry("u1", grade="A")])
        assert "A 级推荐" in msgs[0].content
        assert "🔥" in msgs[0].content

    def test_empty(self):
        assert "信息雷达" in render_dingtalk([])[0].content

    def test_segmentation(self):
        entries = [_scored_entry(f"u{i}", summary="x" * 5000) for i in range(10)]
        msgs = render_dingtalk(entries, delivery=DeliveryConfig(max_entries_per_message=3))
        assert sum(m.entry_count for m in msgs) == 10


class TestRenderWeekly:
    def test_renders(self):
        entries = [_scored_entry("u1", "AI", grade="A"), _scored_entry("u2", "Rust", grade="B")]
        msgs = render_weekly(entries)
        assert "周报" in msgs[0].content
        assert "AI" in msgs[0].content

    def test_empty(self):
        assert "周报" in render_weekly([])[0].content


class TestValidate:
    def test_valid(self):
        assert validate_feishu_json('{"a": 1}')

    def test_invalid(self):
        assert not validate_feishu_json("not json {")
