"""Tests for delivery/failed_digests.py — disk persistence + retry."""
from __future__ import annotations

from infodigest.delivery.failed_digests import (
    FailedDigest,
    increment_retries,
    load_failed,
    remove_failed,
    save_failed,
)


class TestSaveLoad:
    def test_save_and_load(self, tmp_path):
        d = str(tmp_path / "failed")
        path = save_failed(d, "feishu", "card content", 5, 0, "timeout", "digest123")
        assert path.exists()
        items = load_failed(d)
        assert len(items) == 1
        assert items[0].channel == "feishu"
        assert items[0].content == "card content"
        assert items[0].entry_count == 5
        assert items[0].error == "timeout"
        assert items[0].digest_id == "digest123"

    def test_load_empty_dir(self, tmp_path):
        d = str(tmp_path / "nonexistent")
        assert load_failed(d) == []

    def test_multiple_items_sorted_oldest_first(self, tmp_path):
        d = str(tmp_path / "failed")
        import time
        save_failed(d, "feishu", "c1", 1, 0, "e1", "d1")
        time.sleep(0.01)
        save_failed(d, "dingtalk", "c2", 2, 1, "e2", "d2")
        items = load_failed(d)
        assert len(items) == 2
        assert items[0].channel == "feishu"
        assert items[1].channel == "dingtalk"

    def test_corrupt_file_skipped(self, tmp_path):
        d = str(tmp_path / "failed")
        (tmp_path / "failed").mkdir()
        (tmp_path / "failed" / "bad.json").write_text("not json")
        save_failed(d, "feishu", "good", 1, 0, "e", "d")
        items = load_failed(d)
        assert len(items) == 1
        assert items[0].content == "good"


class TestRemove:
    def test_remove_after_retry(self, tmp_path):
        d = str(tmp_path / "failed")
        save_failed(d, "feishu", "c1", 1, 0, "e1", "d1")
        items = load_failed(d)
        assert len(items) == 1
        removed = remove_failed(d, items[0])
        assert removed
        assert load_failed(d) == []

    def test_remove_nonexistent(self, tmp_path):
        d = str(tmp_path / "failed")
        fd = FailedDigest(channel="x", content="c", entry_count=0, batch_index=0, error="e", created_at=0, digest_id="d")
        assert not remove_failed(d, fd)


class TestIncrementRetries:
    def test_increment(self, tmp_path):
        d = str(tmp_path / "failed")
        save_failed(d, "feishu", "c1", 1, 0, "e1", "d1")
        items = load_failed(d)
        assert items[0].retries == 0
        increment_retries(d, items[0])
        items2 = load_failed(d)
        assert items2[0].retries == 1

    def test_increment_nonexistent_dir(self, tmp_path):
        d = str(tmp_path / "nonexistent")
        fd = FailedDigest(channel="x", content="c", entry_count=0, batch_index=0, error="e", created_at=0, digest_id="d")
        increment_retries(d, fd)  # should not error

    def test_increment_no_match(self, tmp_path):
        d = str(tmp_path / "failed")
        save_failed(d, "feishu", "c1", 1, 0, "e1", "d1")
        fd = FailedDigest(channel="other", content="c", entry_count=0, batch_index=9, error="e", created_at=999, digest_id="d")
        increment_retries(d, fd)
        items = load_failed(d)
        assert items[0].retries == 0  # unchanged, no match

    def test_increment_skips_corrupt_file(self, tmp_path):
        d = str(tmp_path / "failed")
        (tmp_path / "failed").mkdir()
        (tmp_path / "failed" / "bad.json").write_text("not json")
        save_failed(d, "feishu", "good", 1, 0, "e", "d")
        items = load_failed(d)
        increment_retries(d, items[0])  # should skip corrupt, increment good
        items2 = load_failed(d)
        assert items2[0].retries == 1


class TestRemoveEdgeCases:
    def test_remove_skips_corrupt_file(self, tmp_path):
        d = str(tmp_path / "failed")
        (tmp_path / "failed").mkdir()
        (tmp_path / "failed" / "bad.json").write_text("not json")
        save_failed(d, "feishu", "good", 1, 0, "e", "d")
        items = load_failed(d)
        removed = remove_failed(d, items[0])
        assert removed  # good file matched and removed despite corrupt sibling


class TestIdempotency:
    def test_save_creates_distinct_files(self, tmp_path):
        d = str(tmp_path / "failed")
        save_failed(d, "feishu", "c1", 1, 0, "e1", "d1")
        import time
        time.sleep(0.01)
        save_failed(d, "feishu", "c2", 2, 1, "e2", "d2")
        items = load_failed(d)
        assert len(items) == 2
