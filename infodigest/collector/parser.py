"""Collector parser: feedparser -> normalized Entry list.

Parses RSS 2.0 / Atom 1.0 / RDF (RSS 1.0), maps fields, cleans HTML via
normalizer. Bad feeds return empty list (never raise).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import feedparser

from ..config import Source
from .normalizer import normalize_title, parse_time, strip_html


@dataclass(frozen=True)
class Entry:
    """A normalized feed entry. uid is the dedup primary key."""

    uid: str
    source_id: str
    title: str
    summary: str
    link: str
    published: datetime | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def _build_entry(item: dict, source: Source) -> Entry | None:
    """Build an Entry from a feedparser item dict. Returns None if no link."""
    link = item.get("link") or ""
    # feedparser falls back to the entry id when no <link href> is present;
    # a urn:uuid / non-http value is not a fetchable link, so skip it.
    if not link or not (link.startswith("http://") or link.startswith("https://")):
        return None

    title_raw = item.get("title") or ""
    title = title_raw.strip()

    # Summary: prefer summary, fallback to content[0].value
    summary_html = item.get("summary") or ""
    if not summary_html:
        contents = item.get("content") or []
        if contents and isinstance(contents, list):
            summary_html = contents[0].get("value", "") if isinstance(contents[0], dict) else ""
    summary = strip_html(summary_html)

    published = parse_time(item.get("published_parsed") or item.get("updated_parsed") or item.get("published") or item.get("updated"))

    # uid = sha1(normalized_title + source_domain)
    import hashlib

    norm_title = normalize_title(title)
    uid = hashlib.sha1(f"{norm_title}{source.domain}".encode("utf-8")).hexdigest()

    raw = {
        "title": title_raw,
        "link": link,
        "summary": summary_html,
        "published": str(published) if published else "",
    }

    # Capture engagement fields if present (HN points/comments)
    for eng_key in ("points", "comments", "wfw_commentrss", "slash_comments"):
        if eng_key in item:
            raw[eng_key] = item[eng_key]

    return Entry(
        uid=uid,
        source_id=source.id,
        title=title,
        summary=summary,
        link=link,
        published=published,
        raw=raw,
    )


def parse(content: bytes | str, source: Source) -> list[Entry]:
    """Parse feed content into a list of Entries. Never raises on bad feeds;
    returns [] on parse failure."""
    if not content:
        return []
    # feedparser accepts bytes or str
    parsed = feedparser.parse(content)
    # feedparser swallows parse errors: a bad feed yields bozo + no entries
    entries: list[Entry] = []
    for item in parsed.get("entries", []):
        try:
            e = _build_entry(item, source)
        except Exception:
            e = None
        if e is not None:
            entries.append(e)
    return entries
