"""Formatter builder: Jinja2 rendering + message segmentation.

Pure build, no LLM. Splits entries into batches by max_entries and max_bytes,
renders each batch with the appropriate channel template. Supports automatic
translation of English entries to Chinese via Google Translate (no LLM).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..collector.parser import Entry
from ..config import CONFIG_DIR, DeliveryConfig, TranslateConfig, utc_now
from .translator import load_cache, save_cache, should_translate, translate_text

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class RenderedMessage:
    """A single rendered message ready to send."""

    content: str
    entry_count: int
    batch_index: int


def _grade_label(grade: str) -> str:
    return {
        "S": "⚡ S级必看",
        "A": "🔥 A级推荐",
        "B": "📌 B级关注",
        "C": "📄 C级",
    }.get(grade, "•")


def _entry_reason(entry: Entry) -> str:
    reason = entry.raw.get("event_reason") or ""
    if reason and reason != "no_event_pattern":
        return f" · {reason}"
    return ""

def _json_escape(text: str) -> str:
    """Escape a string for embedding inside a JSON string value."""
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    text = text.replace("\r", "\\r")
    text = text.replace("\t", "\\t")
    return text


def _make_env(templates_dir: Path) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["grade_label"] = _grade_label
    env.filters["json_escape"] = _json_escape
    return env


def _estimate_bytes(content: str) -> int:
    return len(content.encode("utf-8"))


def _translate_entry(entry: Entry, target_lang: str, source_langs: dict[str, str]) -> Entry:
    """Translate an entry's title and summary if source language differs from target.
    Returns a new Entry with translated fields in raw['title_zh'] and raw['summary_zh'].
    """
    src_lang = source_langs.get(entry.source_id, "")
    if not should_translate(src_lang, target_lang):
        return entry
    new_raw = dict(entry.raw)
    title_zh = translate_text(entry.title, source_lang=src_lang, target_lang=target_lang)
    if title_zh:
        new_raw["title_zh"] = title_zh
    if entry.summary:
        summary_zh = translate_text(entry.summary, source_lang=src_lang, target_lang=target_lang)
        if summary_zh:
            new_raw["summary_zh"] = summary_zh
    if new_raw != entry.raw:
        return Entry(
            uid=entry.uid, source_id=entry.source_id, title=entry.title,
            summary=entry.summary, link=entry.link, published=entry.published,
            raw=new_raw,
        )
    return entry


def translate_entries(
    entries: list[Entry],
    translate_cfg: TranslateConfig,
    source_langs: dict[str, str] | None = None,
) -> list[Entry]:
    """Translate entries that are in a different language than target.
    source_langs: mapping of source_id -> language code (e.g. "en", "zh").
    Uses disk cache for translation persistence across runs."""
    if not translate_cfg.enabled:
        return entries
    if source_langs is None:
        source_langs = {}
    cache_path = Path(translate_cfg.cache_file)
    if not cache_path.is_absolute():
        cache_path = REPO_ROOT / cache_path
    load_cache(cache_path)
    translated = [_translate_entry(e, translate_cfg.target_lang, source_langs) for e in entries]
    save_cache()
    return translated


def segment_entries(
    entries: list[Entry],
    max_entries: int = 20,
    max_bytes: int = 30000,
) -> list[list[Entry]]:
    """Split entries into batches respecting both entry-count and byte-size limits."""
    batches: list[list[Entry]] = []
    current: list[Entry] = []
    current_bytes = 0

    for e in entries:
        e_bytes = len((e.title + e.summary + e.link).encode("utf-8")) + 200
        would_exceed_count = len(current) >= max_entries
        would_exceed_bytes = current_bytes + e_bytes > max_bytes
        if current and (would_exceed_count or would_exceed_bytes):
            batches.append(current)
            current = []
            current_bytes = 0
        current.append(e)
        current_bytes += e_bytes

    if current:
        batches.append(current)
    return batches


def _build_feishu_card(
    entries: list[Entry],
    sources: list[str],
    generated_at: str,
) -> dict:
    """Build a Feishu interactive card JSON structure programmatically."""
    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{generated_at}** · 共 {len(entries)} 条 · 来源 {len(sources)} · info",
            },
        },
        {"tag": "hr"},
    ]

    for entry in entries:
        title = entry.title
        link = entry.link
        summary = entry.summary[:120] + ("..." if len(entry.summary) > 120 else "")
        grade = entry.grade
        label = _grade_label(grade)
        reason = _entry_reason(entry)

        # Build translation block if available
        title_zh = entry.raw.get("title_zh", "")
        summary_zh = entry.raw.get("summary_zh", "")
        translated_block = ""
        if title_zh:
            translated_block = f"\n📝 {title_zh}"
        if summary_zh:
            translated_block += f"\n{summary_zh[:100]}"

        if grade in ("S", "A"):
            tag = "S 必看" if grade == "S" else "A 推荐"
            emoji = "⚡" if grade == "S" else "🔥"
            elements.append(
                {
                    "tag": "note",
                    "elements": [{
                        "tag": "lark_md",
                        "content": (
                            f"{emoji} **[{tag}]** [{title}]({link}){reason}\n"
                            f"{summary}{translated_block}"
                        ),
                    }],
                }
            )
        else:
            content = (
                f"{label} [{title}]({link}){reason}\n{summary}{translated_block}"
                if summary
                else f"{label} [{title}]({link}){reason}{translated_block}"
            )
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": content},
                }
            )

    elements.append(
        {
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": "信息雷达 · 宁可少说，不可凑数"}],
        }
    )

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "📡 信息雷达 · 精选"},
                "template": "blue",
            },
            "elements": elements,
        },
    }


def render_feishu(
    entries: list[Entry],
    sources: list[str] | None = None,
    templates_dir: Path | None = None,
    delivery: DeliveryConfig | None = None,
    translate_cfg: TranslateConfig | None = None,
    source_langs: dict[str, str] | None = None,
) -> list[RenderedMessage]:
    """Render entries into Feishu interactive card JSON messages, segmented."""
    d = delivery or DeliveryConfig()
    if translate_cfg and translate_cfg.enabled:
        entries = translate_entries(entries, translate_cfg, source_langs)
    batches = segment_entries(entries, d.max_entries_per_message, d.max_message_bytes) or [[]]
    src_list = sources or []
    generated_at = utc_now().strftime("%Y-%m-%d %H:%M UTC")
    messages = []
    for i, batch in enumerate(batches):
        card = _build_feishu_card(batch, src_list, generated_at)
        content = json.dumps(card, ensure_ascii=False, indent=2)
        messages.append(RenderedMessage(content=content, entry_count=len(batch), batch_index=i))
    return messages


def render_dingtalk(
    entries: list[Entry],
    sources: list[str] | None = None,
    templates_dir: Path | None = None,
    delivery: DeliveryConfig | None = None,
    translate_cfg: TranslateConfig | None = None,
    source_langs: dict[str, str] | None = None,
) -> list[RenderedMessage]:
    """Render entries into DingTalk markdown messages, segmented."""
    tdir = templates_dir or (CONFIG_DIR / "templates")
    env = _make_env(tdir)
    template = env.get_template("dingtalk_md.j2")
    d = delivery or DeliveryConfig()
    if translate_cfg and translate_cfg.enabled:
        entries = translate_entries(entries, translate_cfg, source_langs)
    batches = segment_entries(entries, d.max_entries_per_message, d.max_message_bytes) or [[]]
    messages = []
    for i, batch in enumerate(batches):
        rendered = template.render(
            entries=batch,
            sources=sources or [],
            generated_at=utc_now().strftime("%Y-%m-%d %H:%M UTC"),
        )
        messages.append(RenderedMessage(content=rendered.strip(), entry_count=len(batch), batch_index=i))
    return messages


def render_weekly(
    entries: list[Entry],
    sources: list[str] | None = None,
    templates_dir: Path | None = None,
    delivery: DeliveryConfig | None = None,
) -> list[RenderedMessage]:
    """Render entries into weekly digest markdown messages, segmented."""
    tdir = templates_dir or (CONFIG_DIR / "templates")
    env = _make_env(tdir)
    template = env.get_template("weekly_digest.j2")
    d = delivery or DeliveryConfig()
    batches = segment_entries(entries, d.max_entries_per_message, d.max_message_bytes) or [[]]
    messages = []
    for i, batch in enumerate(batches):
        rendered = template.render(
            entries=batch,
            sources=sources or [],
            generated_at=utc_now().strftime("%Y-%m-%d %H:%M UTC"),
        )
        messages.append(RenderedMessage(content=rendered.strip(), entry_count=len(batch), batch_index=i))
    return messages


def _clean_json(text: str) -> str:
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return text


def validate_feishu_json(content: str) -> bool:
    """Validate that rendered Feishu content is parseable JSON."""
    try:
        json.loads(content)
        return True
    except (json.JSONDecodeError, TypeError):
        return False
