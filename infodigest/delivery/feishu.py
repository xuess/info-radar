"""Delivery Feishu channel: interactive card webhook with optional signing.

Sends JSON card payload to FEISHU_WEBHOOK. If FEISHU_SECRET is set, computes
the signature (timestamp + secret -> HMAC-SHA256) per Feishu custom bot spec.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

import httpx

from ..config import DeliveryConfig
from .base import SendResult
from .limiter import TokenBucket, make_feishu_limiter


def _sign(secret: str, timestamp: int) -> str:
    """Feishu webhook signature: base64(HMAC-SHA256(timestamp + "\n" + secret, ''))."""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


class FeishuChannel:
    """Feishu custom bot webhook channel."""

    name = "feishu"

    def __init__(
        self,
        webhook: str | None = None,
        secret: str | None = None,
        delivery: DeliveryConfig | None = None,
        limiter: TokenBucket | None = None,
        client: httpx.Client | None = None,
    ):
        self.webhook = webhook or os.environ.get("FEISHU_WEBHOOK", "")
        self.secret = secret or os.environ.get("FEISHU_SECRET", "")
        self.delivery = delivery or DeliveryConfig()
        self.limiter = limiter or make_feishu_limiter(self.delivery.feishu_rate_per_min)
        self._client = client  # injected for testing
        self._owns_client = client is None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=10.0)
            self._owns_client = True
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def send(self, content: str) -> SendResult:
        """Send a Feishu interactive card. `content` is the card JSON string."""
        if not self.webhook:
            return SendResult(ok=False, error="FEISHU_WEBHOOK not configured")

        # Rate limit
        if not self.limiter.acquire(timeout=30.0):
            return SendResult(ok=False, error="rate limit timeout")

        # The formatter already produces the full {msg_type, card} JSON.
        # If a secret is set, add timestamp + sign fields.
        import json

        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return SendResult(ok=False, error="invalid card JSON")

        if self.secret:
            timestamp = int(time.time())
            payload["timestamp"] = str(timestamp)
            payload["sign"] = _sign(self.secret, timestamp)

        body = json.dumps(payload)
        client = self._get_client()
        last_err: str | None = None
        for attempt in range(self.delivery.retry_max):
            try:
                resp = client.post(self.webhook, content=body, headers={"Content-Type": "application/json"})
                # Feishu returns 200 even on logical errors; check body
                if resp.status_code == 200:
                    try:
                        rdata = resp.json()
                        if rdata.get("StatusCode") == 0 or rdata.get("code") == 0 or rdata.get("StatusMessage") == "success":
                            return SendResult(ok=True, status=200, message=str(rdata))
                        # Logical error — don't retry indefinitely
                        err = f"feishu logical error: {rdata}"
                        last_err = err
                    except Exception:
                        return SendResult(ok=True, status=200)
                else:
                    last_err = f"HTTP {resp.status_code}"
                # 5xx -> retry
                if 500 <= resp.status_code < 600:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                # Non-retryable
                break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_err = str(exc)
                time.sleep(1.0 * (attempt + 1))
                continue

        return SendResult(ok=False, error=last_err or "send failed")
