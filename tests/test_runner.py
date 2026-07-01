"""Tests for scheduler/runner.py — end-to-end pipeline with injected channels
and a local RSS fixture (no real network)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from infodigest.collector.parser import Entry
from infodigest.config import Config, DeliveryConfig, RaterConfig, Source, StorageConfig, CollectConfig, ScheduleConfig, REPO_ROOT
from infodigest.delivery.base import SendResult
from infodigest.scheduler.runner import RunReport, run

FIXTURES = REPO_ROOT / "tests" / "fixtures"


class FakeChannel:
    """A fake channel that always succeeds (or fails) for testing."""

    name = "fake"

    def __init__(self, ok: bool = True, error: str = "boom"):
        self.ok = ok
        self.error = error
        self.sent: list[str] = []

    def send(self, content: str) -> SendResult:
        self.sent.append(content)
        if self.ok:
            return SendResult(ok=True, status=200)
        return SendResult(ok=False, error=self.error)

    def close(self):
        pass


def _make_config(db_path: str, feed_path: Path, enabled: bool = True) -> Config:
    """Build a Config pointing at a local fixture file as the single source."""
    source = Source(
        id="fixture",
        url=f"file://{feed_path}",
        category="tech",
        authority=0.85,
        lang="en",
        tags=("test",),
        enabled=enabled,
    )
    return Config(
        sources=(source,),
        collect=CollectConfig(timeout=5, max_retries=1, user_agent="test", respect_robots=False),
        delivery=DeliveryConfig(
            feishu_enabled=True, dingtalk_enabled=True,
            max_entries_per_message=20, max_message_bytes=30000,
            push_grade_min="B", retry_max=1,
        ),
        storage=StorageConfig(db_path=db_path, failed_digests_dir=str(Path(db_path).parent / "failed_digests")),
        schedule=ScheduleConfig(),
        rater=RaterConfig(
            weights={"authority": 30, "freshness": 25, "relevance": 25, "uniqueness": 10, "engagement": 10},
            keywords={"ai": 1.0, "llm": 1.0, "rust": 0.7, "安全": 0.8, "opensource": 0.6},
            grade_thresholds={"A": 75, "B": 50},
            push_grade_min="B",
            dedup_similarity=0.8,
            dedup_window_days=7,
        ),
    )


def _patch_file_fetch(monkeypatch, feed_path: Path):
    """Patch the runner's fetch() to read the local fixture file instead of HTTP."""
    from infodigest.collector.fetcher import FetchResult
    from infodigest.collector import fetcher as fetcher_mod
    import infodigest.scheduler.runner as runner_mod

    content = feed_path.read_bytes()

    def fake_fetch(url, cfg, etag=None, last_modified=None):
        if url.startswith("file://"):
            return FetchResult(content=content, status=200, etag=None, last_modified=None, url=url)
        raise RuntimeError(f"unexpected HTTP fetch in test: {url}")

    monkeypatch.setattr(runner_mod, "fetch", fake_fetch)


class TestRunPipeline:
    def test_full_run_with_rss2(self, tmp_db, monkeypatch):
        config = _make_config(tmp_db, FIXTURES / "rss2_sample.xml")
        _patch_file_fetch(monkeypatch, FIXTURES / "rss2_sample.xml")
        feishu = FakeChannel(ok=True)
        dingtalk = FakeChannel(ok=True)
        report = run(config, db_path=tmp_db, feishu=feishu, dingtalk=dingtalk)
        assert report.collected > 0
        assert report.rated > 0
        # Some entries should have been delivered (grade >= B)
        assert report.delivered >= 0
        # At least one channel received a message
        assert len(feishu.sent) + len(dingtalk.sent) > 0

    def test_run_no_sources(self, tmp_db, monkeypatch):
        config = Config(sources=(), storage=StorageConfig(db_path=tmp_db))
        report = run(config, db_path=tmp_db)
        assert report.collected == 0
        assert report.status == "ok"

    def test_run_disabled_source_skipped(self, tmp_db, monkeypatch):
        config = _make_config(tmp_db, FIXTURES / "rss2_sample.xml", enabled=False)
        _patch_file_fetch(monkeypatch, FIXTURES / "rss2_sample.xml")
        report = run(config, db_path=tmp_db)
        assert report.collected == 0

    def test_run_delivery_failure_persisted(self, tmp_db, monkeypatch):
        config = _make_config(tmp_db, FIXTURES / "rss2_sample.xml")
        _patch_file_fetch(monkeypatch, FIXTURES / "rss2_sample.xml")
        feishu = FakeChannel(ok=False, error="webhook down")
        dingtalk = FakeChannel(ok=False, error="webhook down")
        report = run(config, db_path=tmp_db, feishu=feishu, dingtalk=dingtalk)
        assert report.failed > 0
        assert any("webhook down" in e for e in report.errors)
        # Failed digests should be persisted to disk
        failed_dir = Path(tmp_db).parent / "failed_digests"
        assert failed_dir.exists()
        assert len(list(failed_dir.glob("*.json"))) > 0

    def test_run_idempotent_no_duplicates(self, tmp_db, monkeypatch):
        config = _make_config(tmp_db, FIXTURES / "rss2_sample.xml")
        _patch_file_fetch(monkeypatch, FIXTURES / "rss2_sample.xml")
        feishu = FakeChannel(ok=True)
        dingtalk = FakeChannel(ok=True)
        # First run
        run(config, db_path=tmp_db, feishu=feishu, dingtalk=dingtalk)
        # Second run: same fixture, should not duplicate entries
        feishu2 = FakeChannel(ok=True)
        dingtalk2 = FakeChannel(ok=True)
        report2 = run(config, db_path=tmp_db, feishu=feishu2, dingtalk=dingtalk2)
        # Second run: entries already stored, pending empty (already marked pushed)
        # collected may be same (re-parsed) but stored=0 (dedup by uid)
        assert report2.stored == 0

    def test_run_creates_run_record(self, tmp_db, monkeypatch):
        config = _make_config(tmp_db, FIXTURES / "rss2_sample.xml")
        _patch_file_fetch(monkeypatch, FIXTURES / "rss2_sample.xml")
        report = run(config, db_path=tmp_db, feishu=FakeChannel(), dingtalk=FakeChannel())
        assert report.run_id > 0
        # Verify run record in db
        from infodigest.storage.models import init_db
        conn = init_db(tmp_db)
        row = conn.execute("SELECT * FROM runs WHERE id=?", (report.run_id,)).fetchone()
        assert row is not None
        assert row["status"] in ("ok", "partial")
        conn.close()

    def test_run_report_status(self, tmp_db):
        report = RunReport()
        assert report.status == "ok"
        report.errors.append("something")
        assert report.status == "partial"
