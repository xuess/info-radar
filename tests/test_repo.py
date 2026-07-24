"""Tests for storage/models.py and storage/repo.py — uses temporary SQLite db."""
from __future__ import annotations


import pytest

from infodigest.collector.parser import Entry
from infodigest.config import Source
from infodigest.rater.scorer import ScoredEntry
from infodigest.storage.models import init_db, migrate
from infodigest.storage.repo import Repo


def _entry(uid: str, title: str = "Test entry", published=None, source_id: str = "test") -> Entry:
    return Entry(
        uid=uid, source_id=source_id, title=title, summary="summary text",
        link=f"https://example.com/{uid}", published=published, raw={"authority": 0.8},
    )


def _source(sid="test") -> Source:
    return Source(id=sid, url="https://example.com/feed", category="tech", authority=0.8, lang="en", tags=("news",))


@pytest.fixture
def repo(tmp_db):
    conn = init_db(tmp_db)
    yield Repo(conn)
    conn.close()


class TestModels:
    def test_migrate_creates_tables(self, tmp_db):
        import sqlite3
        conn = sqlite3.connect(tmp_db)
        migrate(conn)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"sources", "entries", "digests", "runs"} <= tables
        conn.close()

    def test_migrate_idempotent(self, tmp_db):
        conn = init_db(tmp_db)
        # Running again should not error
        migrate(conn)
        conn.close()

    def test_init_db_creates_parent_dir(self, tmp_path):
        db = str(tmp_path / "sub" / "deep" / "test.db")
        conn = init_db(db)
        conn.close()
        import os
        assert os.path.exists(db)


class TestSources:
    def test_upsert_source(self, repo):
        repo.upsert_source(_source("hn"), etag='"abc"', last_modified="Mon")
        etag, lm = repo.get_source_cache("hn")
        assert etag == '"abc"'
        assert lm == "Mon"

    def test_upsert_source_updates_cache(self, repo):
        repo.upsert_source(_source("hn"))
        repo.set_source_cache("hn", '"v2"', "Tue")
        etag, lm = repo.get_source_cache("hn")
        assert etag == '"v2"'
        assert lm == "Tue"

    def test_get_cache_nonexistent_source(self, repo):
        assert repo.get_source_cache("nope") == (None, None)

    def test_disable_source(self, repo):
        repo.upsert_source(_source("hn"))
        repo.disable_source("hn")
        etag, lm = repo.get_source_cache("hn")
        # still has cache but disabled flag set
        row = repo.conn.execute("SELECT enabled FROM sources WHERE id='hn'").fetchone()
        assert row["enabled"] == 0


class TestEntries:
    def test_upsert_new_entries(self, repo):
        entries = [_entry("u1"), _entry("u2"), _entry("u3")]
        n = repo.upsert_entries(entries)
        assert n == 3

    def test_upsert_idempotent_skips_existing(self, repo):
        entries = [_entry("u1"), _entry("u2")]
        repo.upsert_entries(entries)
        # Re-insert same -> 0 new
        n = repo.upsert_entries(entries)
        assert n == 0

    def test_upsert_mixed_new_and_existing(self, repo):
        repo.upsert_entries([_entry("u1")])
        n = repo.upsert_entries([_entry("u1"), _entry("u2")])
        assert n == 1

    def test_upsert_empty(self, repo):
        assert repo.upsert_entries([]) == 0

    def test_update_score(self, repo):
        e = _entry("u1", title="AI news")
        repo.upsert_entries([e])
        se = ScoredEntry(entry=e, raw_score=80.0, grade="A", components={})
        repo.update_score(se)
        row = repo.conn.execute("SELECT raw_score, grade FROM entries WHERE uid='u1'").fetchone()
        assert row["raw_score"] == 80.0
        assert row["grade"] == "A"

    def test_recent_titles(self, repo):
        repo.upsert_entries([_entry("u1", "AI breakthrough"), _entry("u2", "Rust news")])
        titles = repo.recent_titles(7)
        assert "AI breakthrough" in titles
        assert "Rust news" in titles

    def test_pending_digest_filters_by_grade(self, repo):
        e1 = _entry("u1", "Grade A")
        e2 = _entry("u2", "Grade B")
        e3 = _entry("u3", "Grade C")
        e4 = _entry("u4", "Grade S")
        repo.upsert_entries([e1, e2, e3, e4])
        repo.update_score(ScoredEntry(entry=e1, raw_score=85, grade="A", components={}))
        repo.update_score(ScoredEntry(entry=e2, raw_score=60, grade="B", components={}))
        repo.update_score(ScoredEntry(entry=e3, raw_score=30, grade="C", components={}))
        repo.update_score(ScoredEntry(entry=e4, raw_score=95, grade="S", components={}))

        pending_b = repo.pending_digest("B")
        uids = {e.uid for e in pending_b}
        assert "u1" in uids and "u2" in uids and "u4" in uids and "u3" not in uids

        pending_a = repo.pending_digest("A")
        assert {e.uid for e in pending_a} == {"u1", "u4"}

        pending_s = repo.pending_digest("S")
        assert {e.uid for e in pending_s} == {"u4"}

        pending_c = repo.pending_digest("C")
        assert len(pending_c) == 4

    def test_pending_digest_excludes_pushed(self, repo):
        e1 = _entry("u1", "Grade A")
        repo.upsert_entries([e1])
        repo.update_score(ScoredEntry(entry=e1, raw_score=85, grade="A", components={}))
        digest_id = repo.create_digest("feishu", 1)
        repo.mark_entries_digest(["u1"], digest_id)
        assert repo.pending_digest("A") == []

    def test_mark_entries_digest(self, repo):
        e1 = _entry("u1")
        e2 = _entry("u2")
        repo.upsert_entries([e1, e2])
        repo.update_score(ScoredEntry(entry=e1, raw_score=85, grade="A", components={}))
        repo.update_score(ScoredEntry(entry=e2, raw_score=60, grade="B", components={}))
        did = repo.create_digest("feishu", 2)
        repo.mark_entries_digest(["u1", "u2"], did)
        rows = repo.conn.execute("SELECT uid, digest_id FROM entries").fetchall()
        for r in rows:
            assert r["digest_id"] == did

    def test_mark_empty_uids_noop(self, repo):
        repo.mark_entries_digest([], "did")
        # should not error


class TestDigests:
    def test_create_and_update_digest(self, repo):
        did = repo.create_digest("feishu", 5, status="pending")
        assert len(did) > 0
        repo.update_digest_status(did, "sent")
        row = repo.conn.execute("SELECT status FROM digests WHERE id=?", (did,)).fetchone()
        assert row["status"] == "sent"

    def test_update_digest_with_error(self, repo):
        did = repo.create_digest("feishu", 3, status="pending")
        repo.update_digest_status(did, "failed", "timeout")
        row = repo.conn.execute("SELECT status, error FROM digests WHERE id=?", (did,)).fetchone()
        assert row["status"] == "failed"
        assert row["error"] == "timeout"


class TestRuns:
    def test_start_and_finish_run(self, repo):
        rid = repo.start_run()
        assert rid > 0
        repo.finish_run(rid, collected=10, deduped=2, rated=8, delivered=8, status="ok")
        row = repo.conn.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        assert row["collected"] == 10
        assert row["deduped"] == 2
        assert row["status"] == "ok"
        assert row["ended_at"] is not None


class TestSourceHealth:
    def test_source_health_empty(self, repo):
        repo.upsert_source(_source("hn"))
        health = repo.source_health(30)
        assert len(health) == 1
        assert health[0]["id"] == "hn"
        assert health[0]["total_entries"] == 0
        assert health[0]["a_ratio"] == 0.0

    def test_source_health_with_entries(self, repo):
        repo.upsert_source(_source("hn"))
        e1 = _entry("u1", "A grade", source_id="hn")
        e2 = _entry("u2", "B grade", source_id="hn")
        e3 = _entry("u3", "C grade", source_id="hn")
        repo.upsert_entries([e1, e2, e3])
        repo.update_score(ScoredEntry(entry=e1, raw_score=85, grade="A", components={}))
        repo.update_score(ScoredEntry(entry=e2, raw_score=60, grade="B", components={}))
        repo.update_score(ScoredEntry(entry=e3, raw_score=30, grade="C", components={}))
        health = repo.source_health(30)
        hn = next(h for h in health if h["id"] == "hn")
        assert hn["total_entries"] == 3
        assert hn["a_count"] == 1
        assert abs(hn["a_ratio"] - 1 / 3) < 0.01

    def test_adjust_authority(self, repo):
        repo.upsert_source(_source("hn"))  # authority 0.8
        e1 = _entry("u1", "A grade", source_id="hn")
        e2 = _entry("u2", "B grade", source_id="hn")
        repo.upsert_entries([e1, e2])
        repo.update_score(ScoredEntry(entry=e1, raw_score=85, grade="A", components={}))
        repo.update_score(ScoredEntry(entry=e2, raw_score=60, grade="B", components={}))
        repo.adjust_authority(base_weight=0.7, recent_weight=0.3)
        row = repo.conn.execute("SELECT authority FROM sources WHERE id='hn'").fetchone()
        # adjusted = 0.7*0.8 + 0.3*0.5 (1 A out of 2) = 0.56 + 0.15 = 0.71
        assert abs(row["authority"] - 0.71) < 0.01

    def test_adjust_authority_no_entries_unchanged(self, repo):
        repo.upsert_source(_source("hn"))  # authority 0.8
        repo.adjust_authority()
        row = repo.conn.execute("SELECT authority FROM sources WHERE id='hn'").fetchone()
        assert row["authority"] == 0.8  # unchanged
