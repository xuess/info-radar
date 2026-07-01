"""Tests for delivery/feishu.py — Feishu webhook channel with mock httpx."""
from __future__ import annotations

import json

import httpx

from infodigest.config import DeliveryConfig
from infodigest.delivery.feishu import FeishuChannel, _sign
from infodigest.delivery.limiter import TokenBucket


def _ok_handler(req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=json.dumps({"StatusCode": 0, "StatusMessage": "success"}))


class TestSign:
    def test_sign_deterministic(self):
        s1 = _sign("secret123", 1700000000)
        s2 = _sign("secret123", 1700000000)
        assert s1 == s2

    def test_sign_different_secret(self):
        s1 = _sign("secret123", 1700000000)
        s2 = _sign("secret456", 1700000000)
        assert s1 != s2

    def test_sign_is_base64(self):
        s = _sign("secret123", 1700000000)
        # base64 alphabet
        import base64
        base64.b64decode(s)  # should not raise


class TestFeishuChannel:
    def test_no_webhook_returns_error(self):
        ch = FeishuChannel(webhook="", delivery=DeliveryConfig(retry_max=1), limiter=TokenBucket(10, 100))
        result = ch.send('{"msg_type":"interactive","card":{}}')
        assert not result.ok
        assert "not configured" in (result.error or "")

    def test_send_success(self):
        captured = {}

        class FakeClient:
            def post(self, url, content=None, headers=None):
                captured["url"] = url
                captured["body"] = json.loads(content)
                return _ok_handler(httpx.Request("POST", url))

            def close(self):
                pass

        ch = FeishuChannel(
            webhook="https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
            secret="",
            delivery=DeliveryConfig(retry_max=1),
            limiter=TokenBucket(10, 100),
            client=FakeClient(),
        )
        card = json.dumps({"msg_type": "interactive", "card": {"elements": []}})
        result = ch.send(card)
        assert result.ok
        assert captured["body"]["msg_type"] == "interactive"

    def test_send_with_secret_adds_sign(self):
        captured = {}

        class FakeClient:
            def post(self, url, content=None, headers=None):
                captured["body"] = json.loads(content)
                return _ok_handler(httpx.Request("POST", url))

            def close(self):
                pass

        ch = FeishuChannel(
            webhook="https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
            secret="mysecret",
            delivery=DeliveryConfig(retry_max=1),
            limiter=TokenBucket(10, 100),
            client=FakeClient(),
        )
        ch.send(json.dumps({"msg_type": "interactive", "card": {}}))
        assert "timestamp" in captured["body"]
        assert "sign" in captured["body"]

    def test_send_logical_error(self):
        class FakeClient:
            def post(self, url, content=None, headers=None):
                return httpx.Response(200, content=json.dumps({"StatusCode": 9499, "StatusMessage": "invalid sign"}))

            def close(self):
                pass

        ch = FeishuChannel(
            webhook="https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
            delivery=DeliveryConfig(retry_max=1),
            limiter=TokenBucket(10, 100),
            client=FakeClient(),
        )
        result = ch.send(json.dumps({"msg_type": "interactive", "card": {}}))
        assert not result.ok
        assert "logical error" in (result.error or "")

    def test_send_invalid_json(self):
        ch = FeishuChannel(
            webhook="https://x.com",
            delivery=DeliveryConfig(retry_max=1),
            limiter=TokenBucket(10, 100),
            client=httpx.Client(transport=httpx.MockTransport(_ok_handler)),
        )
        result = ch.send("not json at all")
        assert not result.ok
        assert "invalid card JSON" in (result.error or "")

    def test_send_5xx_retries(self):
        calls = {"n": 0}

        class FakeClient:
            def post(self, url, content=None, headers=None):
                calls["n"] += 1
                if calls["n"] < 3:
                    return httpx.Response(500)
                return httpx.Response(200, content=json.dumps({"StatusCode": 0}))

            def close(self):
                pass

        import time
        ch = FeishuChannel(
            webhook="https://x.com",
            delivery=DeliveryConfig(retry_max=3),
            limiter=TokenBucket(10, 100),
            client=FakeClient(),
        )
        # avoid real sleep delays
        orig = time.sleep
        time.sleep = lambda s: None
        try:
            result = ch.send(json.dumps({"msg_type": "interactive", "card": {}}))
        finally:
            time.sleep = orig
        assert result.ok
        assert calls["n"] == 3
