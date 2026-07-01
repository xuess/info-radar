"""Delivery failed-digest persistence: write undelivered messages to disk
for retry on the next run. Stored as JSON files in data/failed_digests/.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path



@dataclass(frozen=True)
class FailedDigest:
    """A digest message that failed to deliver, persisted for retry."""

    channel: str
    content: str
    entry_count: int
    batch_index: int
    error: str
    created_at: float  # unix timestamp
    digest_id: str
    retries: int = 0


def _failed_dir(base_dir: str) -> Path:
    d = Path(base_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_failed(
    base_dir: str,
    channel: str,
    content: str,
    entry_count: int,
    batch_index: int,
    error: str,
    digest_id: str,
) -> Path:
    """Persist a failed digest message to disk. Returns the file path."""
    d = _failed_dir(base_dir)
    fd = FailedDigest(
        channel=channel,
        content=content,
        entry_count=entry_count,
        batch_index=batch_index,
        error=error,
        created_at=time.time(),
        digest_id=digest_id,
    )
    fname = f"{int(time.time() * 1000)}_{channel}_{batch_index}.json"
    path = d / fname
    with path.open("w", encoding="utf-8") as fh:
        json.dump({
            "channel": fd.channel,
            "content": fd.content,
            "entry_count": fd.entry_count,
            "batch_index": fd.batch_index,
            "error": fd.error,
            "created_at": fd.created_at,
            "digest_id": fd.digest_id,
            "retries": fd.retries,
        }, fh, ensure_ascii=False, indent=2)
    return path


def load_failed(base_dir: str) -> list[FailedDigest]:
    """Load all persisted failed digests, oldest first."""
    d = Path(base_dir)
    if not d.exists():
        return []
    items: list[FailedDigest] = []
    for path in sorted(d.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            items.append(FailedDigest(
                channel=data["channel"],
                content=data["content"],
                entry_count=data["entry_count"],
                batch_index=data["batch_index"],
                error=data["error"],
                created_at=data["created_at"],
                digest_id=data["digest_id"],
                retries=data.get("retries", 0),
            ))
        except (json.JSONDecodeError, KeyError):
            # Corrupt file — skip but don't crash
            continue
    return items


def remove_failed(base_dir: str, digest: FailedDigest) -> bool:
    """Remove a failed-digest file after successful retry. Best-effort match
    by created_at + channel + batch_index."""
    d = Path(base_dir)
    if not d.exists():
        return False
    for path in d.glob("*.json"):
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if (
                data.get("channel") == digest.channel
                and data.get("batch_index") == digest.batch_index
                and data.get("created_at") == digest.created_at
            ):
                path.unlink()
                return True
        except (json.JSONDecodeError, OSError):
            continue
    return False


def increment_retries(base_dir: str, digest: FailedDigest) -> None:
    """Increment the retry count on a persisted failed digest."""
    d = Path(base_dir)
    if not d.exists():
        return
    for path in d.glob("*.json"):
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if (
                data.get("channel") == digest.channel
                and data.get("batch_index") == digest.batch_index
                and data.get("created_at") == digest.created_at
            ):
                data["retries"] = data.get("retries", 0) + 1
                data["error"] = digest.error
                with path.open("w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False, indent=2)
                return
        except (json.JSONDecodeError, OSError):
            continue
