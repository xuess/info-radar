"""OPML → feeds.yaml importer.

Reads an OPML file (XML with outline elements), extracts feed URLs/titles,
and merges them into config/feeds.yaml as new sources (enabled: false by
default for safety).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

from infodigest.config import CONFIG_DIR


def parse_opml(opml_path: str | Path) -> list[dict]:
    """Parse an OPML file and return a list of source dicts.

    Each dict has: id, url, title, category. id is slugified from title.
    """
    tree = ET.parse(str(opml_path))
    root = tree.getroot()
    sources = []
    seen_urls = set()
    for outline in root.iter("outline"):
        xml_url = outline.get("xmlUrl") or ""
        title = outline.get("title") or outline.get("text") or ""
        if not xml_url:
            continue
        if xml_url in seen_urls:
            continue
        seen_urls.add(xml_url)
        category = outline.get("category") or ""
        # Walk up for category if not set
        if not category:
            parent = outline
            while parent is not None:
                ptext = parent.get("text") or parent.get("title") or ""
                if ptext and parent.get("xmlUrl") is None:
                    category = ptext
                    break
                parent = None  # ElementTree has no parent pointer; stop
        slug = _slugify(title or xml_url)
        sources.append({
            "id": slug,
            "url": xml_url,
            "title": title,
            "category": category.lower() or "imported",
        })
    return sources


def _slugify(text: str) -> str:
    """Make a slug from text: lowercase, alnum + underscore."""
    import re

    s = text.lower().strip()
    s = re.sub(r"[^\w]+", "_", s)
    s = s.strip("_")
    return s or "source"


def merge_into_feeds(sources: list[dict], feeds_path: str | Path, default_authority: float = 0.5) -> int:
    """Merge new sources into feeds.yaml. New sources added with enabled: false.
    Returns count of newly added sources."""
    feeds_path = Path(feeds_path)
    if feeds_path.exists():
        with feeds_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    else:
        data = {}
    existing = data.get("sources") or []
    existing_ids = {s["id"] for s in existing}
    existing_urls = {s["url"] for s in existing}

    added = 0
    for src in sources:
        if src["id"] in existing_ids or src["url"] in existing_urls:
            continue
        existing.append({
            "id": src["id"],
            "url": src["url"],
            "category": src["category"],
            "authority": default_authority,
            "lang": "",
            "tags": [],
            "enabled": False,  # new imports start disabled
        })
        existing_ids.add(src["id"])
        existing_urls.add(src["url"])
        added += 1

    data["sources"] = existing
    feeds_path.parent.mkdir(parents=True, exist_ok=True)
    with feeds_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import OPML feeds into feeds.yaml")
    parser.add_argument("opml", help="path to OPML file")
    parser.add_argument("--feeds", default=str(CONFIG_DIR / "feeds.yaml"), help="target feeds.yaml path")
    parser.add_argument("--authority", type=float, default=0.5, help="default authority for new sources")
    args = parser.parse_args(argv)

    sources = parse_opml(args.opml)
    print(f"Parsed {len(sources)} feeds from {args.opml}")
    added = merge_into_feeds(sources, args.feeds, default_authority=args.authority)
    print(f"Added {added} new sources to {args.feeds} (enabled=false, review and enable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
