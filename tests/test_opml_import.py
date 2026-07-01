"""Tests for scripts/opml_import.py — OPML parsing and feeds.yaml merge."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# scripts/ is not a package; add to path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from opml_import import _slugify, main, merge_into_feeds, parse_opml

OPML_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>My Feeds</title></head>
  <body>
    <outline title="Tech" text="Tech">
      <outline title="Hacker News" type="rss" xmlUrl="https://hnrss.org/frontpage" htmlUrl="https://news.ycombinator.com" />
      <outline title="Rust Blog" type="rss" xmlUrl="https://blog.rust-lang.org/feed.xml" htmlUrl="https://blog.rust-lang.org" />
    </outline>
    <outline title="AI" text="AI">
      <outline title="MIT Tech Review" type="rss" xmlUrl="https://www.technologyreview.com/feed/" />
    </outline>
    <outline title="No URL" text="No URL" />
    <outline title="Duplicate" type="rss" xmlUrl="https://hnrss.org/frontpage" />
  </body>
</opml>
"""


@pytest.fixture
def opml_file(tmp_path):
    f = tmp_path / "feeds.opml"
    f.write_text(OPML_SAMPLE)
    return f


class TestParseOpml:
    def test_parses_feeds(self, opml_file):
        sources = parse_opml(opml_file)
        assert len(sources) == 3  # duplicate excluded

    def test_extracts_urls(self, opml_file):
        sources = parse_opml(opml_file)
        urls = [s["url"] for s in sources]
        assert "https://hnrss.org/frontpage" in urls
        assert "https://blog.rust-lang.org/feed.xml" in urls

    def test_extracts_titles(self, opml_file):
        sources = parse_opml(opml_file)
        titles = [s["title"] for s in sources]
        assert "Hacker News" in titles

    def test_skips_no_url(self, opml_file):
        sources = parse_opml(opml_file)
        assert not any(s["title"] == "No URL" for s in sources)

    def test_dedup_by_url(self, opml_file):
        sources = parse_opml(opml_file)
        urls = [s["url"] for s in sources]
        assert len(urls) == len(set(urls))


class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello_world"

    def test_special_chars(self):
        assert _slugify("AI & ML! Blog") == "ai_ml_blog"

    def test_empty(self):
        assert _slugify("") == "source"

    def test_chinese(self):
        # Chinese chars are \w in Python regex
        assert _slugify("机器之心") == "机器之心"


class TestMergeIntoFeeds:
    def test_merge_new_sources(self, opml_file, tmp_path):
        feeds = tmp_path / "feeds.yaml"
        sources = parse_opml(opml_file)
        added = merge_into_feeds(sources, feeds)
        assert added == 3
        with feeds.open() as fh:
            data = yaml.safe_load(fh)
        assert len(data["sources"]) == 3
        assert all(s["enabled"] is False for s in data["sources"])

    def test_merge_no_duplicates(self, opml_file, tmp_path):
        feeds = tmp_path / "feeds.yaml"
        sources = parse_opml(opml_file)
        merge_into_feeds(sources, feeds)
        # Merge again -> 0 new
        added = merge_into_feeds(sources, feeds)
        assert added == 0

    def test_merge_into_existing_yaml(self, tmp_path):
        feeds = tmp_path / "feeds.yaml"
        feeds.write_text("sources:\n  - id: existing\n    url: https://x.com/feed\n    authority: 0.5\n    enabled: true\n")
        sources = [{"id": "new_src", "url": "https://y.com/feed", "title": "New", "category": "tech"}]
        added = merge_into_feeds(sources, feeds)
        assert added == 1
        with feeds.open() as fh:
            data = yaml.safe_load(fh)
        assert len(data["sources"]) == 2

    def test_merge_empty_sources(self, tmp_path):
        feeds = tmp_path / "feeds.yaml"
        added = merge_into_feeds([], feeds)
        assert added == 0


class TestMain:
    def test_main_runs(self, opml_file, tmp_path, capsys):
        feeds = tmp_path / "feeds.yaml"
        rc = main([str(opml_file), "--feeds", str(feeds)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Added" in out
        assert feeds.exists()
