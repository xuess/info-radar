"""Delivery DingTalk channel: markdown webhook with HMAC-SHA256 signing.

Sends markdown message to DINGTALK_WEBHOOK. Signs with DINGTALK_SECRET per
DingTalk custom robot spec: sign = base64(HMAC-SHA256(timestamp + "\n" + secret)).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import urllib.parse

import httpx

from ..config import DeliveryConfig
from .base import SendResult
from .limiter import TokenBucket, make_dingtalk_limiter


def _sign(secret: str, timestamp: int) -> str:
    """DingTalk signature: base64(HMAC-SHA256(secret, timestamp+'\n'+secret))."""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return urllib.parse.quote_plus(base64.b64encode(hmac_code).decode("utf-8"))


def _build_payload(content: str) -> dict:
    """Build DingTalk markdown message payload from rendered markdown."""
    # Extract title from first markdown heading line
    title = "InfoDigest"
    for line in content.splitlines():
        s = line.strip()
        if s.startswith("#"):
            title = s.lstrip("#").strip() or title
            break
    return {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": content},
    }


class DingTalkChannel:
    """DingTalk custom bot webhook channel."""

    name = "dingtalk"

    def __init__(
        self,
        webhook: str | None = None,
        secret: str | None = None,
        delivery: DeliveryConfig | None = None,
        limiter: TokenBucket | None = None,
        client: httpx.Client | None = None,
    ):
        self.webhook = webhook or os.environ.get("DINGTALK_WEBHOOK", "")
        self.secret = secret or os.environ.get("DINGTALK_SECRET", "")
        self.delivery = delivery or DeliveryConfig()
        self.limiter = limiter or make_dingtalk_limiter(self.delivery.dingtalk_rate_per_min)
        self._client = client
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

    def _signed_url(self, timestamp: int) -> str:
        """Append timestamp + sign query params to webhook URL."""
        sign = _sign(self.secret, timestamp)
        sep = "&" if "?" in self.webhook else "?"
        return f"{self.webhook}{sep}timestamp={timestamp}&sign={sign}"

    def send(self, content: str) -> SendResult:
        """Send a DingTalk markdown message."""
        if not self.webhook:
            return SendResult(ok=False, error="DINGTALK_WEBHOOK not configured")

        if not self.limiter.acquire(timeout=30.0):
            return SendResult(ok=False, error="rate limit timeout")

        payload = _build_payload(content)
        body = __import__("json").dumps(payload)
        client = self._get_client()
        last_err: str | None = None

        for attempt in range(self.delivery.retry_max):
            try:
                timestamp = int(time.time() * 1000)  # DingTalk uses ms
                url = self._signed_url(timestamp) if self.secret else self.webhook
                resp = client.post(url, content=body, headers={"Content-Type": "application/json"})
                if resp.status_code == 200:
                    try:
                        rdata = resp.json()
                        if rdata.get("errcode") == 0:
                            return SendResult(ok=True, status=200, message=str(rdata))
                        last_err = f"dingtalk errcode={rdata.get('errcode')}: {rdata.get('errmsg')}"
                    except Exception:
                        return SendResult(ok=True, status=200)
                else:
                    last_err = f"HTTP {resp.status_code}"
                if 500 <= resp.status_code < 600:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_err = str(exc)
                time.sleep(1.0 * (attempt + 1))
                continue

        return SendResult(ok=False, error=last_err or "send failed")
