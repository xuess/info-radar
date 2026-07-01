"""Tests for rater/scorer.py"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from infodigest.collector.parser import Entry
from infodigest.config import RaterConfig
from infodigest.rater.scorer import ScoreContext, ScoredEntry, grade_for, score, score_many


def _entry(title: str = "Test", summary: str = "", published=None, authority=0.5, raw=None) -> Entry:
    r = {"authority": authority}
    if raw:
        r.update(raw)
    return Entry(
        uid="x",
        source_id="test",
        title=title,
        summary=summary,
        link="https://example.com/x",
        published=published,
        raw=r,
    )


def _rater(**kw) -> RaterConfig:
    defaults = dict(
        weights={"authority": 30, "freshness": 25, "relevance": 25, "uniqueness": 10, "engagement": 10},
        freshness_half_life_hours=72.0,
        max_age_hours=168.0,
        relevance_target=3.0,
        engagement_threshold=200.0,
        grade_thresholds={"A": 75, "B": 50},
        push_grade_min="B",
        keywords={"ai": 1.0, "llm": 1.0, "安全": 0.8},
        penalty_words={"震惊": 0.5},
        dedup_similarity=0.8,
        dedup_window_days=7,
    )
    defaults.update(kw)
    return RaterConfig(**defaults)


NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


class TestFreshness:
    def test_zero_delta_max_freshness(self):
        e = _entry(published=NOW)
        ctx = ScoreContext(now=NOW, rater=_rater())
        se = score(e, ctx)
        assert se.components["freshness"] == 1.0

    def test_no_published_treated_as_now(self):
        e = _entry(published=None)
        ctx = ScoreContext(now=NOW, rater=_rater())
        se = score(e, ctx)
        assert se.components["freshness"] == 1.0

    def test_half_life_decay(self):
        # 72h ago -> exp(-1) ≈ 0.368
        e = _entry(published=NOW - timedelta(hours=72))
        ctx = ScoreContext(now=NOW, rater=_rater())
        se = score(e, ctx)
        assert abs(se.components["freshness"] - 0.368) < 0.01

    def test_older_than_max_age_is_zero(self):
        e = _entry(published=NOW - timedelta(hours=200))
        ctx = ScoreContext(now=NOW, rater=_rater())
        se = score(e, ctx)
        assert se.components["freshness"] == 0.0

    def test_future_published_clamped_to_max(self):
        e = _entry(published=NOW + timedelta(hours=10))
        ctx = ScoreContext(now=NOW, rater=_rater())
        se = score(e, ctx)
        assert se.components["freshness"] == 1.0


class TestRelevance:
    def test_no_keywords_neutral(self):
        e = _entry(title="random news", summary="nothing here")
        ctx = ScoreContext(now=NOW, rater=_rater(keywords={}))
        se = score(e, ctx)
        assert se.components["relevance"] == 0.5

    def test_title_hit_full_weight(self):
        e = _entry(title="AI breakthrough", summary="")
        ctx = ScoreContext(now=NOW, rater=_rater(keywords={"ai": 1.0}))
        se = score(e, ctx)
        # 1.0 / 3.0 target
        assert abs(se.components["relevance"] - 1 / 3) < 0.01

    def test_summary_hit_reduced_weight(self):
        e = _entry(title="nothing", summary="AI content here")
        ctx = ScoreContext(now=NOW, rater=_rater(keywords={"ai": 1.0}))
        se = score(e, ctx)
        # 0.4*1.0 / 3.0
        assert abs(se.components["relevance"] - 0.4 / 3) < 0.01

    def test_multiple_hits_clamped_to_one(self):
        e = _entry(title="AI LLM", summary="AI and LLM everywhere")
        ctx = ScoreContext(now=NOW, rater=_rater(keywords={"ai": 1.0, "llm": 1.0}))
        se = score(e, ctx)
        # title: ai+llm=2.0, summary: 0.4+0.4=0.8 -> 2.8/3.0
        assert abs(se.components["relevance"] - 2.8 / 3) < 0.01

    def test_penalty_word_reduces(self):
        e = _entry(title="震惊 AI breakthrough", summary="")
        ctx = ScoreContext(now=NOW, rater=_rater(keywords={"ai": 1.0}, penalty_words={"震惊": 0.5}))
        se = score(e, ctx)
        # (1.0 - 0.5) / 3.0
        assert abs(se.components["relevance"] - 0.5 / 3) < 0.01


class TestUniqueness:
    def test_no_history_unique(self):
        e = _entry(title="novel content here")
        ctx = ScoreContext(now=NOW, rater=_rater(), recent_titles=[])
        se = score(e, ctx)
        assert se.components["uniqueness"] == 1.0

    def test_identical_in_history_zero(self):
        e = _entry(title="AI breakthrough")
        ctx = ScoreContext(now=NOW, rater=_rater(), recent_titles=["AI breakthrough"])
        se = score(e, ctx)
        assert se.components["uniqueness"] == 0.0

    def test_partial_overlap(self):
        e = _entry(title="AI breakthrough model")
        ctx = ScoreContext(now=NOW, rater=_rater(), recent_titles=["AI breakthrough news"])
        se = score(e, ctx)
        # jaccard: {ai,breakthrough,model} vs {ai,breakthrough,news} = 2/4=0.5
        # uniqueness = 0.5
        assert abs(se.components["uniqueness"] - 0.5) < 0.01

    def test_empty_title_unique(self):
        e = _entry(title="")
        ctx = ScoreContext(now=NOW, rater=_rater(), recent_titles=["something"])
        se = score(e, ctx)
        assert se.components["uniqueness"] == 1.0


class TestEngagement:
    def test_no_engagement_zero(self):
        e = _entry(title="x")
        ctx = ScoreContext(now=NOW, rater=_rater())
        se = score(e, ctx)
        assert se.components["engagement"] == 0.0

    def test_points_normalized(self):
        e = _entry(title="x", raw={"points": 100})
        ctx = ScoreContext(now=NOW, rater=_rater(engagement_threshold=200))
        se = score(e, ctx)
        assert se.components["engagement"] == 0.5

    def test_points_above_threshold_clamped(self):
        e = _entry(title="x", raw={"points": 500})
        ctx = ScoreContext(now=NOW, rater=_rater(engagement_threshold=200))
        se = score(e, ctx)
        assert se.components["engagement"] == 1.0

    def test_comments_field(self):
        e = _entry(title="x", raw={"comments": 50})
        ctx = ScoreContext(now=NOW, rater=_rater(engagement_threshold=100))
        se = score(e, ctx)
        assert se.components["engagement"] == 0.5


class TestAuthority:
    def test_default_authority(self):
        e = _entry(title="x", authority=0.5)
        ctx = ScoreContext(now=NOW, rater=_rater())
        se = score(e, ctx)
        assert se.components["authority"] == 0.5

    def test_high_authority(self):
        e = _entry(title="x", authority=0.9)
        ctx = ScoreContext(now=NOW, rater=_rater())
        se = score(e, ctx)
        assert se.components["authority"] == 0.9

    def test_clamped_above_one(self):
        e = _entry(title="x", authority=1.5)
        ctx = ScoreContext(now=NOW, rater=_rater())
        se = score(e, ctx)
        assert se.components["authority"] == 1.0


class TestTotalScore:
    def test_score_in_range(self):
        e = _entry(title="AI breakthrough", summary="LLM content", published=NOW, authority=0.9)
        ctx = ScoreContext(now=NOW, rater=_rater())
        se = score(e, ctx)
        assert 0 <= se.raw_score <= 100

    def test_perfect_high_score(self):
        # Fresh, high authority, high relevance, unique, high engagement
        e = _entry(title="AI LLM agent", summary="AI LLM agent reasoning", published=NOW, authority=1.0, raw={"points": 1000})
        ctx = ScoreContext(now=NOW, rater=_rater(), recent_titles=[])
        se = score(e, ctx)
        # all components ~1.0 -> score ~100
        assert se.raw_score >= 95
        assert se.grade == "A"

    def test_old_low_relevance_low_score(self):
        e = _entry(title="random old news", summary="boring", published=NOW - timedelta(hours=200), authority=0.3)
        ctx = ScoreContext(now=NOW, rater=_rater(), recent_titles=[])
        se = score(e, ctx)
        assert se.raw_score < 50
        assert se.grade == "C"

    def test_grade_thresholds(self):
        rater = _rater(grade_thresholds={"A": 75, "B": 50})
        assert grade_for(80, rater) == "A"
        assert grade_for(75, rater) == "A"
        assert grade_for(60, rater) == "B"
        assert grade_for(50, rater) == "B"
        assert grade_for(49, rater) == "C"
        assert grade_for(0, rater) == "C"


class TestScoreMany:
    def test_batch_scoring(self):
        entries = [
            _entry(title="AI news", published=NOW, authority=0.9),
            _entry(title="old post", published=NOW - timedelta(hours=200), authority=0.3),
        ]
        ctx = ScoreContext(now=NOW, rater=_rater())
        results = score_many(entries, ctx)
        assert len(results) == 2
        assert all(isinstance(r, ScoredEntry) for r in results)
        assert results[0].raw_score > results[1].raw_score

    def test_empty_batch(self):
        ctx = ScoreContext(now=NOW, rater=_rater())
        assert score_many([], ctx) == []


class TestScorerEdgeCases:
    def test_score_context_build_with_now(self):
        from infodigest.rater.scorer import ScoreContext
        ctx = ScoreContext.build(_rater(), recent_titles=["a", "b"], now=NOW)
        assert ctx.now == NOW
        assert ctx.recent_titles == ("a", "b")

    def test_score_context_build_defaults_now(self):
        from infodigest.rater.scorer import ScoreContext
        ctx = ScoreContext.build(_rater())
        assert ctx.now is not None  # utc_now()

    def test_score_with_naive_published(self):
        # published without tzinfo should be treated as UTC
        from datetime import datetime
        naive = datetime(2026, 7, 2, 12, 0)  # no tzinfo
        e = _entry(title="x", published=naive)
        ctx = ScoreContext(now=NOW, rater=_rater())
        se = score(e, ctx)
        assert se.components["freshness"] == 1.0  # same time -> delta 0

    def test_engagement_invalid_value_skipped(self):
        e = _entry(title="x", raw={"points": "not_a_number"})
        ctx = ScoreContext(now=NOW, rater=_rater())
        se = score(e, ctx)
        assert se.components["engagement"] == 0.0

    def test_score_without_rater_uses_defaults(self):
        # ctx.rater = None -> scorer falls back to RaterConfig() defaults
        e = _entry(title="AI news", published=NOW, authority=0.9)
        ctx = ScoreContext(now=NOW, rater=None)
        se = score(e, ctx)
        assert 0 <= se.raw_score <= 100
        assert se.grade in ("A", "B", "C")

    def test_jaccard_one_empty_one_not(self):
        from infodigest.rater.scorer import _jaccard
        a = frozenset("hello".split())
        b = frozenset()
        # one empty, one not -> union non-empty -> 0/len
        assert _jaccard(a, b) == 0.0
