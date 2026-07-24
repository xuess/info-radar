"""Rater subpackage: deterministic rule-based scoring + curation."""

from .curator import CurateResult, curate, curate_from_scored, scored_to_entry
from .event_history import EventHistory
from .scorer import ScoreContext, ScoredEntry, score, score_many

__all__ = [
    "CurateResult",
    "EventHistory",
    "ScoreContext",
    "ScoredEntry",
    "curate",
    "curate_from_scored",
    "score",
    "score_many",
    "scored_to_entry",
]
