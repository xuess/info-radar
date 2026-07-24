"""Tests for rater/curator.py — quotas, silence, noise, link gates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from infodigest.collector.parser import Entry
from infodigest.config import RaterConfig
from infodigest.rater.curator import curate
from infodigest.rater.event_history import EventHistory
from infodigest.storage.models import init_db

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


def _e(uid, title, grade="B", score=60.0, link="https://example.com/x", summary=""):
    return Entry(
        uid=uid,
        source_id="t",
        title=title,
        summary=summary,
        link=link,
        published=NOW,
        raw={"grade": grade, "raw_score": score},
    )


@pytest.fixture
def rater():
    return RaterConfig(
        noise_patterns=("震惊", "必看", "clickbait"),
        daily_quotas={"S": 2, "A": 3, "B": 4},
        min_push_score=50.0,
        allow_empty_digest=True,
        require_link_for_high_grade=True,
        dedup_hours=48,
        dedup_similarity=0.75,
        novelty_keywords=("首次",),
    )


class TestCurateFilters:
    def test_noise_dropped(self, rater):
        entries = [_e("1", "震惊！必看 AI 新闻", grade="A", score=80)]
        result = curate(entries, rater, now=NOW)
        assert result.entries == []
        assert result.reasons.get("noise", 0) == 1

    def test_no_link_drops_high_grade(self, rater):
        entries = [_e("1", "Important AI release", grade="A", score=80, link="")]
        result = curate(entries, rater, now=NOW)
        assert result.entries == []
        assert result.reasons.get("no_link", 0) == 1

    def test_b_without_link_kept(self, rater):
        # B grade does not require link
        entries = [_e("1", "Minor update", grade="B", score=55, link="")]
        result = curate(entries, rater, now=NOW)
        assert len(result.entries) == 1

    def test_below_min_score(self, rater):
        entries = [_e("1", "Meh", grade="B", score=40)]
        result = curate(entries, rater, now=NOW)
        assert result.entries == []
        assert result.reasons.get("below_min_score", 0) == 1

    def test_silent_when_empty(self, rater):
        result = curate([], rater, now=NOW)
        assert result.silent is True
        assert result.entries == []


class TestQuotas:
    def test_quota_trim(self, rater):
        entries = [
            _e(f"s{i}", f"S event {i}", grade="S", score=95 - i) for i in range(5)
        ]
        result = curate(entries, rater, daily_state={"S": 0, "A": 0, "B": 0}, now=NOW)
        assert len(result.entries) == 2  # quota S=2
        assert result.reasons.get("quota_S", 0) == 3

    def test_respects_existing_daily_state(self, rater):
        entries = [_e("s1", "S event", grade="S", score=95)]
        result = curate(
            entries, rater, daily_state={"S": 2, "A": 0, "B": 0}, now=NOW
        )
        assert result.entries == []
        assert result.reasons.get("quota_S", 0) == 1

    def test_sort_by_score(self, rater):
        entries = [
            _e("b", "Low", grade="B", score=55),
            _e("a", "High", grade="A", score=85),
        ]
        result = curate(entries, rater, now=NOW)
        assert result.entries[0].uid == "a"


class TestHistoryIntegration:
    def test_48h_filter(self, rater, tmp_path):
        conn = init_db(str(tmp_path / "c.db"))
        hist = EventHistory(conn, rater)
        hist.record("Duplicate news", 80, now=NOW)
        entries = [_e("1", "Duplicate news", grade="A", score=80)]
        result = curate(entries, rater, history=hist, now=NOW)
        assert result.entries == []


class TestCurateExtra:
    def test_downgrade_demotes_grade(self, rater, tmp_path):
        conn = init_db(str(tmp_path / "d.db"))
        hist = EventHistory(conn, rater)
        # 3 appearances, last > 48h ago → downgraded but still output
        t0 = NOW - timedelta(days=5)
        for i in range(3):
            hist.record("Recurring story", 80, now=t0 + timedelta(days=i))
        entries = [_e("1", "Recurring story", grade="A", score=80)]
        result = curate(entries, rater, history=hist, now=NOW)
        assert len(result.entries) == 1
        assert result.entries[0].raw.get("downgraded") is True
        assert result.entries[0].raw.get("grade") == "B"

    def test_grade_c_dropped(self, rater):
        entries = [_e("1", "Low value", grade="C", score=80)]
        result = curate(entries, rater, now=NOW)
        assert result.entries == []
        assert result.reasons.get("grade_c", 0) == 1

    def test_curate_from_scored(self, rater, tmp_path):
        from infodigest.rater.curator import curate_from_scored
        from infodigest.rater.scorer import ScoredEntry

        conn = init_db(str(tmp_path / "e.db"))
        e = _e("1", "Good news", grade="A", score=80)
        se = ScoredEntry(entry=e, raw_score=80, grade="A", components={})
        result = curate_from_scored([se], rater, conn=conn, now=NOW)
        assert len(result.entries) == 1

    def test_invalid_noise_regex_falls_back(self, rater):
        # Invalid regex pattern should fall back to substring
        r = RaterConfig(
            noise_patterns=("(unclosed",),
            daily_quotas={"S": 3, "A": 8, "B": 12},
            min_push_score=50,
            allow_empty_digest=True,
            require_link_for_high_grade=False,
        )
        entries = [_e("1", "contains (unclosed stuff", grade="B", score=60)]
        result = curate(entries, r, now=NOW)
        assert result.entries == []
