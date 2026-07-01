"""Formatter builder: Jinja2 rendering + message segmentation.

Pure build, no LLM. Splits entries into batches by max_entries and max_bytes,
renders each batch with the appropriate channel template.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..collector.parser import Entry
from ..config import CONFIG_DIR, DeliveryConfig, utc_now


@dataclass(frozen=True)
class RenderedMessage:
    """A single rendered message ready to send."""

    content: str
    entry_count: int
    batch_index: int


def _grade_label(grade: str) -> str:
    return {"A": "🔥 A级推荐", "B": "📌 B级关注", "C": "📄 C级"}.get(grade, "•")


def _make_env(templates_dir: Path) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["grade_label"] = _grade_label
    return env


def _estimate_bytes(content: str) -> int:
    """Estimate serialized byte size of a message (UTF-8)."""
    return len(content.encode("utf-8"))


def segment_entries(
    entries: list[Entry],
    max_entries: int = 20,
    max_bytes: int = 30000,
) -> list[list[Entry]]:
    """Split entries into batches respecting both entry-count and byte-size
    limits. Byte estimate uses the rendered title+summary length."""
    batches: list[list[Entry]] = []
    current: list[Entry] = []
    current_bytes = 0

    for e in entries:
        # Estimate per-entry bytes: title + summary + link + overhead
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


def render_feishu(
    entries: list[Entry],
    sources: list[str] | None = None,
    templates_dir: Path | None = None,
    delivery: DeliveryConfig | None = None,
) -> list[RenderedMessage]:
    """Render entries into Feishu interactive card JSON messages, segmented."""
    tdir = templates_dir or (CONFIG_DIR / "templates")
    env = _make_env(tdir)
    template = env.get_template("feishu_card.j2")
    d = delivery or DeliveryConfig()
    batches = segment_entries(entries, d.max_entries_per_message, d.max_message_bytes) or [[]]
    messages = []
    for i, batch in enumerate(batches):
        rendered = template.render(
            entries=batch,
            sources=sources or [],
            generated_at=utc_now().strftime("%Y-%m-%d %H:%M UTC"),
        )
        # Validate JSON (the template produces JSON; strip whitespace jinja leaks)
        content = rendered.strip()
        # Remove trailing commas before closing brackets (jinja loop artifact)
        content = _clean_json(content)
        messages.append(RenderedMessage(content=content, entry_count=len(batch), batch_index=i))
    return messages


def render_dingtalk(
    entries: list[Entry],
    sources: list[str] | None = None,
    templates_dir: Path | None = None,
    delivery: DeliveryConfig | None = None,
) -> list[RenderedMessage]:
    """Render entries into DingTalk markdown messages, segmented."""
    tdir = templates_dir or (CONFIG_DIR / "templates")
    env = _make_env(tdir)
    template = env.get_template("dingtalk_md.j2")
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
    """Clean up common Jinja2 rendering artifacts in JSON output: trailing
    commas before } or ]."""
    import re

    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return text


def validate_feishu_json(content: str) -> bool:
    """Validate that rendered Feishu content is parseable JSON.
    Applies the same trailing-comma cleanup the renderer uses, so callers
    can validate raw template output."""
    try:
        json.loads(_clean_json(content))
        return True
    except (json.JSONDecodeError, TypeError):
        return False
