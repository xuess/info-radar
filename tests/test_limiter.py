"""Tests for delivery/limiter.py — token bucket rate limiter."""
from __future__ import annotations

import time

from infodigest.delivery.limiter import (
    TokenBucket,
    make_dingtalk_limiter,
    make_feishu_limiter,
)


class TestTokenBucket:
    def test_initial_burst(self):
        # Starts full — can acquire up to capacity immediately
        bucket = TokenBucket(capacity=5, refill_per_sec=5 / 60)
        for _ in range(5):
            assert bucket.try_acquire()

    def test_try_acquire_depleted(self):
        bucket = TokenBucket(capacity=2, refill_per_sec=0.01)
        assert bucket.try_acquire()
        assert bucket.try_acquire()
        assert not bucket.try_acquire()

    def test_refill_over_time(self):
        bucket = TokenBucket(capacity=1, refill_per_sec=100.0)  # very fast refill
        assert bucket.try_acquire()
        assert not bucket.try_acquire()
        time.sleep(0.05)  # 0.05s * 100 = 5 tokens refilled
        assert bucket.try_acquire()

    def test_acquire_blocks_until_available(self):
        # Capacity 1, already used; refills fast
        bucket = TokenBucket(capacity=1, refill_per_sec=100.0)
        assert bucket.try_acquire()  # use the initial token
        start = time.monotonic()
        ok = bucket.acquire(timeout=1.0)
        elapsed = time.monotonic() - start
        assert ok
        assert elapsed < 1.0

    def test_acquire_timeout(self):
        bucket = TokenBucket(capacity=0, refill_per_sec=0.0)  # never refills
        ok = bucket.acquire(timeout=0.3)
        assert not ok

    def test_feishu_limiter_factory(self):
        limiter = make_feishu_limiter(rate_per_min=5)
        assert limiter.capacity == 5
        assert abs(limiter.refill_per_sec - 5 / 60) < 0.001

    def test_dingtalk_limiter_factory(self):
        limiter = make_dingtalk_limiter(rate_per_min=20)
        assert limiter.capacity == 20
        assert abs(limiter.refill_per_sec - 20 / 60) < 0.001
