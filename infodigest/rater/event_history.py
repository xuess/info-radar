"""Event history: temporal dedup, decay, novelty (no LLM).

Aligned with openclaw event-dedup.py:
- 48h within last_seen → suppress (unless novelty keywords)
- 7d count >= 3 → downgrade flag (still output but lower score)
- count >= 5 → force archive (never output)
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..collector.dedup import title_similarity
from ..config import RaterConfig, utc_now

_NON_WORD_RE = re.compile(r"[^\w\u4e00-\u9fff]", re.UNICODE)


def _normalize_title(title: str) -> str:
    return _NON_WORD_RE.sub("", title).lower().strip()


def title_hash(title: str) -> str:
    return hashlib.md5(_normalize_title(title).encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class HistoryDecision:
    """Result of should_output check."""

    should_output: bool
    reason: str
    event_id: str | None = None
    downgraded: bool = False
    days_since_first: float = 0.0
    count: int = 0


@dataclass(frozen=True)
class DecayResult:
    """Decay and novelty adjustment for a title."""

    decay: float
    novelty: float
    days_since_first: float
    count: int


class EventHistory:
    """SQLite-backed event history for temporal curation."""

    def __init__(self, conn: sqlite3.Connection, rater: RaterConfig | None = None):
        self.conn = conn
        self.rater = rater or RaterConfig()

    def find_existing(self, title: str, threshold: float | None = None) -> str | None:
        """Find matching event_history id by title similarity."""
        thresh = threshold if threshold is not None else self.rater.dedup_similarity
        best_id = None
        best_score = 0.0
        rows = self.conn.execute(
            "SELECT id, title FROM event_history"
        ).fetchall()
        for row in rows:
            sim = title_similarity(title, row["title"])
            if sim >= thresh and sim > best_score:
                best_score = sim
                best_id = row["id"]
        return best_id

    def should_output(
        self,
        title: str,
        now: datetime | None = None,
        text_for_novelty: str = "",
    ) -> HistoryDecision:
        """Decide whether this title should be pushed."""
        now = now or utc_now()
        event_id = self.find_existing(title)
        if not event_id:
            return HistoryDecision(True, "new_event")

        row = self.conn.execute(
            "SELECT * FROM event_history WHERE id=?", (event_id,)
        ).fetchone()
        if row is None:
            return HistoryDecision(True, "new_event")

        first_seen = datetime.fromisoformat(row["first_seen"])
        last_seen = datetime.fromisoformat(row["last_seen"])
        if first_seen.tzinfo is None:
            from datetime import timezone

            first_seen = first_seen.replace(tzinfo=timezone.utc)
        if last_seen.tzinfo is None:
            from datetime import timezone

            last_seen = last_seen.replace(tzinfo=timezone.utc)

        count = int(row["count"] or 1)
        hours_since_last = (now - last_seen).total_seconds() / 3600.0
        days_since_first = (now - first_seen).total_seconds() / 86400.0

        if count >= self.rater.force_archive_count:
            return HistoryDecision(
                False,
                f"force_archived (appeared {count} times)",
                event_id=event_id,
                count=count,
                days_since_first=days_since_first,
            )

        has_novelty = self._has_novelty(text_for_novelty or title)
        if hours_since_last < self.rater.dedup_hours:
            if has_novelty or bool(row["has_new_development"]):
                return HistoryDecision(
                    True,
                    "new_development_within_48h",
                    event_id=event_id,
                    count=count,
                    days_since_first=days_since_first,
                )
            return HistoryDecision(
                False,
                f"within_48h (last seen {hours_since_last:.1f}h ago)",
                event_id=event_id,
                count=count,
                days_since_first=days_since_first,
            )

        downgraded = (
            days_since_first <= self.rater.downgrade_window_days
            and count >= self.rater.downgrade_count
        )
        if downgraded:
            return HistoryDecision(
                True,
                f"downgraded ({count} times in {days_since_first:.0f}d)",
                event_id=event_id,
                downgraded=True,
                count=count,
                days_since_first=days_since_first,
            )

        return HistoryDecision(
            True,
            "stale_enough",
            event_id=event_id,
            count=count,
            days_since_first=days_since_first,
        )

    def compute_decay(
        self,
        title: str,
        grade_hint: str = "B",
        text_for_novelty: str = "",
        now: datetime | None = None,
    ) -> DecayResult:
        """Compute decay and novelty for a title based on history."""
        now = now or utc_now()
        event_id = self.find_existing(title)
        if not event_id:
            novelty = self.rater.novelty_bonus if self._has_novelty(text_for_novelty or title) else 0.0
            # Novelty on brand-new events is not applied (nothing to boost against)
            return DecayResult(decay=0.0, novelty=0.0, days_since_first=0.0, count=0)

        row = self.conn.execute(
            "SELECT * FROM event_history WHERE id=?", (event_id,)
        ).fetchone()
        if row is None:
            return DecayResult(0.0, 0.0, 0.0, 0)

        first_seen = datetime.fromisoformat(row["first_seen"])
        if first_seen.tzinfo is None:
            from datetime import timezone

            first_seen = first_seen.replace(tzinfo=timezone.utc)
        days = max(0.0, (now - first_seen).total_seconds() / 86400.0)
        count = int(row["count"] or 1)
        rate = float(self.rater.decay_rates.get(grade_hint, 10))
        decay = rate * days
        if (
            count >= self.rater.downgrade_count
            and days <= self.rater.downgrade_window_days
        ):
            decay += 10.0
        novelty = 0.0
        if self._has_novelty(text_for_novelty or title):
            novelty = float(self.rater.novelty_bonus)
        return DecayResult(
            decay=decay, novelty=novelty, days_since_first=days, count=count
        )

    def record(
        self,
        title: str,
        score: float = 50.0,
        now: datetime | None = None,
    ) -> str:
        """Record (or update) an event after successful push. Returns event id."""
        now = now or utc_now()
        now_iso = now.isoformat()
        event_id = self.find_existing(title)
        has_novelty = 1 if self._has_novelty(title) else 0

        if event_id:
            self.conn.execute(
                """
                UPDATE event_history
                SET last_seen=?, count=count+1, last_score=?,
                    has_new_development=CASE WHEN ?=1 THEN 1 ELSE has_new_development END
                WHERE id=?
                """,
                (now_iso, score, has_novelty, event_id),
            )
        else:
            event_id = title_hash(title)
            # Avoid PK collision on hash
            existing = self.conn.execute(
                "SELECT id FROM event_history WHERE id=?", (event_id,)
            ).fetchone()
            if existing:
                event_id = f"{event_id}_{int(now.timestamp())}"
            self.conn.execute(
                """
                INSERT INTO event_history
                  (id, title, first_seen, last_seen, count, last_score, has_new_development)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (event_id, title, now_iso, now_iso, score, has_novelty),
            )
        self.conn.commit()
        return event_id

    def record_many(
        self,
        titles: list[str],
        scores: list[float] | None = None,
        now: datetime | None = None,
    ) -> int:
        scores = scores or [50.0] * len(titles)
        for i, title in enumerate(titles):
            sc = scores[i] if i < len(scores) else 50.0
            self.record(title, sc, now=now)
        return len(titles)

    def get_trends(self, days: int = 7, now: datetime | None = None) -> list[dict]:
        """Return events with count>=2 in the last N days."""
        now = now or utc_now()
        cutoff = (now - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            """
            SELECT title, count, first_seen, last_seen, last_score
            FROM event_history
            WHERE last_seen >= ? AND count >= 2
            ORDER BY count DESC, last_score DESC
            """,
            (cutoff,),
        ).fetchall()
        return [
            {
                "title": r["title"],
                "count": r["count"],
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
                "last_score": r["last_score"],
            }
            for r in rows
        ]

    def cleanup(self, now: datetime | None = None) -> int:
        """Remove history older than history_cleanup_days. Returns removed count."""
        now = now or utc_now()
        cutoff = (now - timedelta(days=self.rater.history_cleanup_days)).isoformat()
        cur = self.conn.execute(
            "DELETE FROM event_history WHERE last_seen < ?", (cutoff,)
        )
        self.conn.commit()
        return cur.rowcount

    def _has_novelty(self, text: str) -> bool:
        low = text.lower()
        for kw in self.rater.novelty_keywords:
            if kw.lower() in low:
                return True
        return False


# ---- daily push state ----

def get_daily_push_state(
    conn: sqlite3.Connection, now: datetime | None = None
) -> dict[str, int]:
    """Return today's S/A/B push counts."""
    now = now or utc_now()
    today = now.strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT s_count, a_count, b_count FROM daily_push_state WHERE date=?",
        (today,),
    ).fetchone()
    if row is None:
        return {"S": 0, "A": 0, "B": 0}
    return {"S": int(row["s_count"]), "A": int(row["a_count"]), "B": int(row["b_count"])}


def update_daily_push_state(
    conn: sqlite3.Connection,
    grades: list[str],
    now: datetime | None = None,
) -> dict[str, int]:
    """Increment today's counts by grades pushed. Returns updated totals."""
    now = now or utc_now()
    today = now.strftime("%Y-%m-%d")
    state = get_daily_push_state(conn, now)
    for g in grades:
        if g in state:
            state[g] += 1
    conn.execute(
        """
        INSERT INTO daily_push_state (date, s_count, a_count, b_count, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
          s_count=excluded.s_count,
          a_count=excluded.a_count,
          b_count=excluded.b_count,
          updated_at=excluded.updated_at
        """,
        (today, state["S"], state["A"], state["B"], now.isoformat()),
    )
    conn.commit()
    return state
