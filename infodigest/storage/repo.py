"""Storage repo: upsert/query/pending operations on SQLite.

Modules pass dataclass Entry/ScoredEntry, never ORM objects.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

from ..collector.parser import Entry
from ..config import Source, utc_now
from ..rater.scorer import ScoredEntry


def _digest_id() -> str:
    """Generate a unique digest ID (time-ordered-ish UUID hex)."""
    return uuid.uuid4().hex


class Repo:
    """Repository over a SQLite connection. Does not own the connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---- sources ----

    def upsert_source(self, source: Source, etag: str | None = None, last_modified: str | None = None) -> None:
        """Insert or update a source record (with incremental cache headers)."""
        now_iso = utc_now().isoformat()
        self.conn.execute(
            """
            INSERT INTO sources (id, url, category, lang, authority, tags, etag, last_modified, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              url=excluded.url, category=excluded.category, lang=excluded.lang,
              authority=excluded.authority, tags=excluded.tags,
              etag=COALESCE(?, sources.etag), last_modified=COALESCE(?, sources.last_modified),
              enabled=excluded.enabled
            """,
            (
                source.id, source.url, source.category, source.lang, source.authority,
                json.dumps(list(source.tags)), etag, last_modified, int(source.enabled), now_iso,
                etag, last_modified,
            ),
        )
        self.conn.commit()

    def get_source_cache(self, source_id: str) -> tuple[str | None, str | None]:
        """Return (etag, last_modified) for a source, for incremental fetch."""
        row = self.conn.execute(
            "SELECT etag, last_modified FROM sources WHERE id=?", (source_id,)
        ).fetchone()
        if row is None:
            return None, None
        return row["etag"], row["last_modified"]

    def set_source_cache(self, source_id: str, etag: str | None, last_modified: str | None) -> None:
        self.conn.execute(
            "UPDATE sources SET etag=?, last_modified=? WHERE id=?",
            (etag, last_modified, source_id),
        )
        self.conn.commit()

    def disable_source(self, source_id: str) -> None:
        self.conn.execute("UPDATE sources SET enabled=0 WHERE id=?", (source_id,))
        self.conn.commit()

    # ---- entries ----

    def upsert_entries(self, entries: Iterable[Entry]) -> int:
        """Insert new entries (skip existing uid). Returns count of newly inserted."""
        now_iso = utc_now().isoformat()
        inserted = 0
        for e in entries:
            cur = self.conn.execute(
                """
                INSERT INTO entries (uid, source_id, title, summary, link, published, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid) DO NOTHING
                """,
                (e.uid, e.source_id, e.title, e.summary, e.link,
                 e.published.isoformat() if e.published else None, now_iso),
            )
            inserted += cur.rowcount
        self.conn.commit()
        return inserted

    def update_score(self, scored: ScoredEntry) -> None:
        """Set raw_score and grade on an existing entry."""
        self.conn.execute(
            "UPDATE entries SET raw_score=?, grade=? WHERE uid=?",
            (scored.raw_score, scored.grade, scored.entry.uid),
        )
        self.conn.commit()

    def recent_titles(self, since_days: int = 7) -> list[str]:
        """Return titles of entries from the last N days for fuzzy dedup."""
        cutoff = (utc_now() - timedelta(days=since_days)).isoformat()
        rows = self.conn.execute(
            "SELECT title FROM entries WHERE created_at >= ? ORDER BY created_at DESC",
            (cutoff,),
        ).fetchall()
        return [r["title"] for r in rows if r["title"]]

    def pending_digest(self, grade_min: str = "B") -> list[Entry]:
        """Return scored entries at or above grade_min that haven't been pushed
        (digest_id IS NULL), newest first."""
        grades = {"A": ["A"], "B": ["A", "B"], "C": ["A", "B", "C"]}
        allowed = grades.get(grade_min, ["A", "B"])
        placeholders = ",".join("?" * len(allowed))
        rows = self.conn.execute(
            f"""
            SELECT uid, source_id, title, summary, link, published
            FROM entries
            WHERE grade IN ({placeholders}) AND digest_id IS NULL
            ORDER BY raw_score DESC, published DESC
            """,
            allowed,
        ).fetchall()
        entries = []
        for r in rows:
            pub = None
            if r["published"]:
                try:
                    pub = datetime.fromisoformat(r["published"])
                except ValueError:
                    pub = None
            entries.append(Entry(
                uid=r["uid"], source_id=r["source_id"], title=r["title"],
                summary=r["summary"] or "", link=r["link"],
                published=pub, raw={},
            ))
        return entries

    def mark_entries_digest(self, uids: list[str], digest_id: str) -> None:
        """Mark entries as belonging to a digest batch."""
        if not uids:
            return
        placeholders = ",".join("?" * len(uids))
        self.conn.execute(
            f"UPDATE entries SET digest_id=? WHERE uid IN ({placeholders})",
            (digest_id, *uids),
        )
        self.conn.commit()

    # ---- digests ----

    def create_digest(self, channel: str, entry_count: int, status: str = "pending", error: str | None = None) -> str:
        digest_id = _digest_id()
        self.conn.execute(
            "INSERT INTO digests (id, created_at, channel, entry_count, status, error) VALUES (?, ?, ?, ?, ?, ?)",
            (digest_id, utc_now().isoformat(), channel, entry_count, status, error),
        )
        self.conn.commit()
        return digest_id

    def update_digest_status(self, digest_id: str, status: str, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE digests SET status=?, error=? WHERE id=?",
            (status, error, digest_id),
        )
        self.conn.commit()

    # ---- runs ----

    def start_run(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, ?)",
            (utc_now().isoformat(), "running"),
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, collected: int = 0, deduped: int = 0, rated: int = 0, delivered: int = 0, status: str = "ok") -> None:
        self.conn.execute(
            "UPDATE runs SET ended_at=?, collected=?, deduped=?, rated=?, delivered=?, status=? WHERE id=?",
            (utc_now().isoformat(), collected, deduped, rated, delivered, status, run_id),
        )
        self.conn.commit()
