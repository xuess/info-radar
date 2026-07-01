"""Tests for collector/normalizer.py"""
from __future__ import annotations

from datetime import datetime, timezone
from time import struct_time

from infodigest.collector.normalizer import (
    normalize_title,
    parse_time,
    strip_html,
)


class TestStripHtml:
    def test_plain_text_passthrough(self):
        assert strip_html("hello world") == "hello world"

    def test_strips_tags(self):
        assert strip_html("<p>hello <b>world</b></p>") == "hello world"

    def test_removes_script_and_style(self):
        html = '<script>alert(1)</script><style>.x{}</style><p>safe</p>'
        assert strip_html(html) == "safe"

    def test_collapses_whitespace(self):
        assert strip_html("<p>  hello\n\n  world  </p>") == "hello world"

    def test_empty_input(self):
        assert strip_html("") == ""
        assert strip_html(None) == ""  # type: ignore[arg-type]

    def test_truncates_long_text(self):
        long = "x" * 600
        result = strip_html(long, summary_max=100)
        assert len(result) == 101  # 100 + ellipsis
        assert result.endswith("…")

    def test_no_truncation_under_limit(self):
        result = strip_html("short", summary_max=100)
        assert result == "short"


class TestNormalizeTitle:
    def test_lowercase(self):
        assert normalize_title("AI Breakthrough") == "ai breakthrough"

    def test_strip_suffix_blog(self):
        assert normalize_title("Some Post - 博客园") == "some post"

    def test_strip_suffix_infoq(self):
        assert normalize_title("Big News | InfoQ") == "big news"

    def test_collapse_whitespace(self):
        assert normalize_title("  hello   world  ") == "hello world"

    def test_remove_punctuation(self):
        assert normalize_title("Hello, World! How?") == "hello world how"

    def test_empty(self):
        assert normalize_title("") == ""
        assert normalize_title(None) == ""  # type: ignore[arg-type]

    def test_chinese_kept(self):
        assert normalize_title("大模型新进展") == "大模型新进展"


class TestParseTime:
    def test_struct_time_to_utc(self):
        st = struct_time((2026, 7, 2, 9, 0, 0, 2, 183, 0))
        dt = parse_time(st)
        assert dt is not None
        assert dt.year == 2026 and dt.month == 7 and dt.day == 2
        assert dt.tzinfo == timezone.utc

    def test_iso_string(self):
        dt = parse_time("2026-07-02T09:00:00Z")
        assert dt is not None
        assert dt.year == 2026
        assert dt.tzinfo == timezone.utc

    def test_rfc822_string(self):
        dt = parse_time("Wed, 02 Jul 2026 09:00:00 GMT")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 7

    def test_none_returns_none(self):
        assert parse_time(None) is None

    def test_garbage_returns_none(self):
        assert parse_time("not a date") is None

    def test_naive_datetime_made_utc(self):
        dt = parse_time(datetime(2026, 7, 2, 9, 0, 0))
        assert dt is not None
        assert dt.tzinfo == timezone.utc
