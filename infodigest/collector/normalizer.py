"""Collector normalizer: HTML cleanup, title normalization, time parsing.

Pure deterministic transforms — no LLM. Used by parser.py to produce a
clean Entry schema.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from time import struct_time

from bs4 import BeautifulSoup

# Common title suffixes to strip, e.g. " - 博客园", " | InfoQ"
_TITLE_SUFFIX_RE = re.compile(
    r"\s*[-–—|]\s*(博客园|InfoQ.*|V2EX|阮一峰.*|Smashing.*|LWN.*)\s*$"
)
# Collapse whitespace
_WS_RE = re.compile(r"\s+")
# Strip leading/trailing punctuation noise for normalization keys
_NON_WORD_RE = re.compile(r"[^\w\u4e00-\u9fff]+")


def strip_html(html: str, summary_max: int = 500) -> str:
    """Strip HTML to plain text: remove script/style, collapse whitespace,
    truncate to summary_max characters."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > summary_max:
        text = text[:summary_max].rstrip() + "…"
    return text


def normalize_title(title: str) -> str:
    """Normalize a title for dedup/keying: lowercase, strip common suffixes,
    collapse whitespace, remove punctuation."""
    if not title:
        return ""
    t = title.strip()
    # Strip common site suffixes
    t = _TITLE_SUFFIX_RE.sub("", t)
    t = t.lower()
    # Replace non-word runs with single space
    t = _NON_WORD_RE.sub(" ", t).strip()
    t = _WS_RE.sub(" ", t)
    return t


def parse_time(value) -> datetime | None:
    """Parse a feedparser time value (struct_time or str) into tz-aware UTC
    datetime. Returns None if unparseable."""
    if value is None:
        return None
    if isinstance(value, struct_time):
        try:
            dt = datetime(
                value.tm_year, value.tm_mon, value.tm_mday,
                value.tm_hour, value.tm_min, value.tm_sec,
                tzinfo=timezone.utc,
            )
            return dt
        except (ValueError, TypeError):
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        # Try a few common formats
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%a, %d %b %Y %H:%M:%S %z",
        ):
            try:
                dt = datetime.strptime(value.strip(), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except ValueError:
                continue
        # Last resort: ISO fromisoformat
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, AttributeError):
            return None
    return None
