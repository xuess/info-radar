"""Tests for rater/event_history.py — temporal dedup, decay, novelty."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from infodigest.config import RaterConfig
from infodigest.rater.event_history import (
    EventHistory,
    get_daily_push_state,
    update_daily_push_state,
)
from infodigest.storage.models import init_db

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def history(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    rater = RaterConfig(
        dedup_hours=48,
        downgrade_count=3,
        downgrade_window_days=7,
        force_archive_count=5,
        novelty_keywords=("发布", "首次", "released"),
        decay_rates={"S": 20, "A": 15, "B": 10, "C": 10},
        novelty_bonus=15.0,
        history_cleanup_days=14,
        dedup_similarity=0.75,
    )
    return EventHistory(conn, rater), conn


class TestShouldOutput:
    def test_new_event(self, history):
        hist, _ = history
        d = hist.should_output("Brand new AI model", now=NOW)
        assert d.should_output
        assert d.reason == "new_event"

    def test_within_48h_suppressed(self, history):
        hist, _ = history
        hist.record("Same story again", score=80, now=NOW - timedelta(hours=10))
        d = hist.should_output("Same story again", now=NOW)
        assert not d.should_output
        assert "within_48h" in d.reason

    def test_novelty_breaks_48h(self, history):
        hist, _ = history
        hist.record("Model update news", score=80, now=NOW - timedelta(hours=10))
        d = hist.should_output(
            "Model update news — 首次发布确认",
            now=NOW,
            text_for_novelty="Model update news — 首次发布确认",
        )
        assert d.should_output
        assert "new_development" in d.reason

    def test_force_archive_after_5(self, history):
        hist, _ = history
        t0 = NOW - timedelta(days=10)
        for i in range(5):
            hist.record("Repeated headline", score=60, now=t0 + timedelta(days=i))
        d = hist.should_output("Repeated headline", now=NOW)
        assert not d.should_output
        assert "force_archived" in d.reason

    def test_downgrade_flag(self, history):
        hist, _ = history
        # Appear 3 times over 5 days, last seen > 48h ago
        t0 = NOW - timedelta(days=5)
        for i in range(3):
            hist.record("Trending topic", score=70, now=t0 + timedelta(days=i))
        d = hist.should_output("Trending topic", now=NOW)
        assert d.should_output
        assert d.downgraded


class TestDecay:
    def test_no_history_zero_decay(self, history):
        hist, _ = history
        r = hist.compute_decay("Never seen", grade_hint="A", now=NOW)
        assert r.decay == 0.0
        assert r.count == 0

    def test_decay_increases_with_days(self, history):
        hist, _ = history
        hist.record("Old story", score=80, now=NOW - timedelta(days=3))
        r = hist.compute_decay("Old story", grade_hint="A", now=NOW)
        assert r.decay >= 15 * 3  # A rate 15/day
        assert r.days_since_first >= 2.9


class TestDailyState:
    def test_empty_then_update(self, history):
        _, conn = history
        state = get_daily_push_state(conn, NOW)
        assert state == {"S": 0, "A": 0, "B": 0}
        updated = update_daily_push_state(conn, ["S", "A", "A", "B"], now=NOW)
        assert updated["S"] == 1
        assert updated["A"] == 2
        assert updated["B"] == 1
        again = get_daily_push_state(conn, NOW)
        assert again == updated

    def test_trends(self, history):
        hist, _ = history
        hist.record("Hot topic", 80, now=NOW - timedelta(days=1))
        hist.record("Hot topic", 80, now=NOW)
        trends = hist.get_trends(7, now=NOW)
        assert any(t["title"] == "Hot topic" and t["count"] >= 2 for t in trends)

    def test_cleanup(self, history):
        hist, _ = history
        hist.record("Ancient", 50, now=NOW - timedelta(days=30))
        hist.record("Recent", 50, now=NOW)
        removed = hist.cleanup(now=NOW)
        assert removed >= 1
        d = hist.should_output("Ancient", now=NOW)
        assert d.reason == "new_event"

    def test_naive_timestamps_treated_as_utc(self, history):
        hist, conn = history
        # Insert naive ISO timestamps directly
        conn.execute(
            """
            INSERT INTO event_history
              (id, title, first_seen, last_seen, count, last_score, has_new_development)
            VALUES ('naive1', 'Naive stamp news', ?, ?, 1, 50, 0)
            """,
            ((NOW - timedelta(hours=10)).replace(tzinfo=None).isoformat(),
             (NOW - timedelta(hours=10)).replace(tzinfo=None).isoformat()),
        )
        conn.commit()
        d = hist.should_output("Naive stamp news", now=NOW)
        assert not d.should_output

    def test_stored_new_development_flag(self, history):
        hist, conn = history
        hist.record("Dev flag story 首次", 80, now=NOW - timedelta(hours=5))
        # Force has_new_development on a similar title without novelty words
        conn.execute(
            "UPDATE event_history SET has_new_development=1, title=?",
            ("Dev flag story",),
        )
        conn.commit()
        d = hist.should_output("Dev flag story", now=NOW)
        assert d.should_output

    def test_hash_collision_suffix(self, history):
        hist, conn = history
        from infodigest.rater.event_history import title_hash

        h = title_hash("Collision title")
        conn.execute(
            """
            INSERT INTO event_history
              (id, title, first_seen, last_seen, count, last_score, has_new_development)
            VALUES (?, 'Other completely different title xyz', ?, ?, 1, 10, 0)
            """,
            (h, NOW.isoformat(), NOW.isoformat()),
        )
        conn.commit()
        # Recording a new distinct title that hashes the same id path should still work
        eid = hist.record("Collision title", 50, now=NOW)
        assert eid  # got an id

    def test_decay_with_downgrade_penalty(self, history):
        hist, _ = history
        t0 = NOW - timedelta(days=4)
        for i in range(3):
            hist.record("Decay topic", 70, now=t0 + timedelta(days=i))
        r = hist.compute_decay("Decay topic", grade_hint="B", now=NOW)
        assert r.decay >= 10  # includes frequency penalty
        assert r.count >= 3

    def test_update_ignores_unknown_grade(self, history):
        _, conn = history
        state = update_daily_push_state(conn, ["S", "C", "X"], now=NOW)
        assert state["S"] == 1
        assert state["A"] == 0
