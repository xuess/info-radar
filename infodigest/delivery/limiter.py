"""Delivery rate limiter: token bucket, per-channel.

Feishu: 5 msgs/min. DingTalk: 20 msgs/min. The limiter blocks until a token
is available, providing natural backpressure.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    """A thread-safe token bucket.

    capacity: max tokens (burst size).
    refill_per_sec: refill rate (rate_per_min / 60).
    """

    capacity: float
    refill_per_sec: float
    _tokens: float = 0.0
    _last_refill: float = 0.0
    _lock: threading.Lock = None  # type: ignore[assignment]

    def __post_init__(self):
        self._tokens = self.capacity
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_sec)
        self._last_refill = now

    def acquire(self, tokens: float = 1.0, timeout: float | None = 30.0) -> bool:
        """Acquire `tokens` tokens, blocking until available or timeout.

        Returns True if acquired, False if timed out.
        """
        deadline = None
        if timeout is not None:
            deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                # How long until enough tokens?
                deficit = tokens - self._tokens
                wait = deficit / self.refill_per_sec if self.refill_per_sec > 0 else 1.0
            if deadline is not None and time.monotonic() + wait > deadline:
                return False
            time.sleep(min(wait, 0.5))

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Non-blocking acquire. Returns True if tokens available now."""
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False


def make_feishu_limiter(rate_per_min: int = 5) -> TokenBucket:
    return TokenBucket(capacity=float(rate_per_min), refill_per_sec=rate_per_min / 60.0)


def make_dingtalk_limiter(rate_per_min: int = 20) -> TokenBucket:
    return TokenBucket(capacity=float(rate_per_min), refill_per_sec=rate_per_min / 60.0)
