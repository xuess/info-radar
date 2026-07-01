"""Formatter builder: Jinja2 rendering + message segmentation.

Pure build, no LLM. Splits entries into batches by max_entries and max_bytes,
renders each batch with the appropriate channel template.
"""
from __future__ import annotations

import json
import re
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
    """Build a Feishu interactive card JSON structure programmatically.
    No template fragility — pure Python dict -> json.dumps."""
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

        if grade == "A":
            elements.append(
                {
                    "tag": "note",
                    "elements": [{"tag": "lark_md", "content": f"🔥 **[A 推荐]** [{title}]({link})\n{summary}"}],
                }
            )
        else:
            content = f"{label} [{title}]({link})\n{summary}" if summary else f"{label} [{title}]({link})"
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": content},
                }
            )

    elements.append(
        {
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": "InfoDigest · 开源自驱信息收集系统"}],
        }
    )

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "📰 InfoDigest 每日推送"},
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
) -> list[RenderedMessage]:
    """Render entries into Feishu interactive card JSON messages, segmented.
    Uses Python dict construction + json.dumps for guaranteed valid JSON."""
    d = delivery or DeliveryConfig()
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
