"""R2.2: Offline scoring regression test — ensures score/grade stability
against a fixed fixture. Catches silent weight/threshold drift.
"""
from __future__ import annotations

from infodigest.config import load_config
from infodigest.rater.scorer import ScoreContext, score

from tests.fixtures.regression_entries import (
    EXPECTED,
    REGRESSION_ENTRIES,
    REGRESSION_NOW,
)


def test_regression_scores_stable():
    """Each regression entry scores within its expected [min, max] band."""
    rater = load_config().rater
    ctx = ScoreContext(now=REGRESSION_NOW, rater=rater, recent_titles=[])
    for entry, (grade, lo, hi) in zip(REGRESSION_ENTRIES, EXPECTED):
        se = score(entry, ctx)
        assert lo <= se.raw_score <= hi, (
            f"{entry.title}: score {se.raw_score} outside [{lo},{hi}], grade={se.grade}"
        )
        assert se.grade == grade, (
            f"{entry.title}: grade {se.grade} != {grade} (score {se.raw_score})"
        )


def test_regression_deterministic():
    """Scoring the same entries twice yields identical results."""
    rater = load_config().rater
    ctx = ScoreContext(now=REGRESSION_NOW, rater=rater, recent_titles=[])
    run1 = [score(e, ctx) for e in REGRESSION_ENTRIES]
    run2 = [score(e, ctx) for e in REGRESSION_ENTRIES]
    for a, b in zip(run1, run2):
        assert a.raw_score == b.raw_score
        assert a.grade == b.grade


def test_regression_ordering():
    """reg1 (fresh+high+keywords+engagement) outscores reg4 (very old)."""
    rater = load_config().rater
    ctx = ScoreContext(now=REGRESSION_NOW, rater=rater, recent_titles=[])
    s1 = score(REGRESSION_ENTRIES[0], ctx)
    s4 = score(REGRESSION_ENTRIES[3], ctx)
    assert s1.raw_score > s4.raw_score
    assert s1.grade in ("S", "A")
    assert s4.grade == "C"
