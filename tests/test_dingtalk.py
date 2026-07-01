"""Tests for delivery/dingtalk.py — DingTalk webhook with HMAC signing."""
from __future__ import annotations

import json

import httpx

from infodigest.config import DeliveryConfig
from infodigest.delivery.dingtalk import DingTalkChannel, _build_payload, _sign
from infodigest.delivery.limiter import TokenBucket


class TestSign:
    def test_sign_deterministic(self):
        assert _sign("sec", 1700000000) == _sign("sec", 1700000000)

    def test_sign_different_secret(self):
        assert _sign("sec1", 1700000000) != _sign("sec2", 1700000000)

    def test_sign_url_encoded(self):
        s = _sign("sec+with/special", 1700000000)
        # quote_plus encodes + and /
        assert "%2B" in s or "%2F" in s or s.isalnum()


class TestBuildPayload:
    def test_extracts_title_from_heading(self):
        content = "# My Title\nbody text here"
        payload = _build_payload(content)
        assert payload["msgtype"] == "markdown"
        assert payload["markdown"]["title"] == "My Title"
        assert payload["markdown"]["text"] == content

    def test_default_title_no_heading(self):
        payload = _build_payload("just text")
        assert payload["markdown"]["title"] == "InfoDigest"


class TestDingTalkChannel:
    def test_no_webhook_returns_error(self):
        ch = DingTalkChannel(webhook="", delivery=DeliveryConfig(retry_max=1), limiter=TokenBucket(10, 100))
        result = ch.send("# Title\nbody")
        assert not result.ok
        assert "not configured" in (result.error or "")

    def test_send_success(self):
        captured = {}

        class FakeClient:
            def post(self, url, content=None, headers=None):
                captured["url"] = url
                captured["body"] = json.loads(content)
                return httpx.Response(200, content=json.dumps({"errcode": 0, "errmsg": "ok"}))

            def close(self):
                pass

        ch = DingTalkChannel(
            webhook="https://oapi.dingtalk.com/robot/send?access_token=xxx",
            secret="",
            delivery=DeliveryConfig(retry_max=1),
            limiter=TokenBucket(10, 100),
            client=FakeClient(),
        )
        result = ch.send("# 📰 InfoDigest\n**test**")
        assert result.ok
        assert captured["body"]["msgtype"] == "markdown"
        assert captured["body"]["markdown"]["title"] == "📰 InfoDigest"

    def test_send_with_secret_appends_sign(self):
        captured = {}

        class FakeClient:
            def post(self, url, content=None, headers=None):
                captured["url"] = url
                return httpx.Response(200, content=json.dumps({"errcode": 0, "errmsg": "ok"}))

            def close(self):
                pass

        ch = DingTalkChannel(
            webhook="https://oapi.dingtalk.com/robot/send?access_token=xxx",
            secret="mysecret",
            delivery=DeliveryConfig(retry_max=1),
            limiter=TokenBucket(10, 100),
            client=FakeClient(),
        )
        ch.send("# Title\nbody")
        assert "timestamp=" in captured["url"]
        assert "sign=" in captured["url"]

    def test_send_errcode_nonzero(self):
        class FakeClient:
            def post(self, url, content=None, headers=None):
                return httpx.Response(200, content=json.dumps({"errcode": 310000, "errmsg": "invalid sign"}))

            def close(self):
                pass

        ch = DingTalkChannel(
            webhook="https://x.com",
            delivery=DeliveryConfig(retry_max=1),
            limiter=TokenBucket(10, 100),
            client=FakeClient(),
        )
        result = ch.send("# Title\nbody")
        assert not result.ok
        assert "errcode=310000" in (result.error or "")

    def test_send_5xx_retries(self):
        calls = {"n": 0}

        class FakeClient:
            def post(self, url, content=None, headers=None):
                calls["n"] += 1
                if calls["n"] < 3:
                    return httpx.Response(503)
                return httpx.Response(200, content=json.dumps({"errcode": 0}))

            def close(self):
                pass

        import time
        ch = DingTalkChannel(
            webhook="https://x.com",
            delivery=DeliveryConfig(retry_max=3),
            limiter=TokenBucket(10, 100),
            client=FakeClient(),
        )
        orig = time.sleep
        time.sleep = lambda s: None
        try:
            result = ch.send("# Title\nbody")
        finally:
            time.sleep = orig
        assert result.ok
        assert calls["n"] == 3

    def test_context_manager(self):
        # Use mock transport to avoid real network
        transport = httpx.MockTransport(lambda req: httpx.Response(200, content=json.dumps({"errcode": 0})))
        with DingTalkChannel(
            webhook="https://oapi.dingtalk.com/robot/send?access_token=x",
            delivery=DeliveryConfig(retry_max=1),
            limiter=TokenBucket(10, 100),
            client=httpx.Client(transport=transport),
        ) as ch:
            result = ch.send("# Title\nbody")
            assert result.ok

    def test_transport_error_retries(self):
        calls = {"n": 0}

        class FakeClient:
            def post(self, url, content=None, headers=None):
                calls["n"] += 1
                raise httpx.ReadTimeout("read timeout")

            def close(self):
                pass

        import time
        ch = DingTalkChannel(
            webhook="https://x.com",
            delivery=DeliveryConfig(retry_max=2),
            limiter=TokenBucket(10, 100),
            client=FakeClient(),
        )
        orig = time.sleep
        time.sleep = lambda s: None
        try:
            result = ch.send("# Title\nbody")
        finally:
            time.sleep = orig
        assert not result.ok
        assert "read timeout" in (result.error or "")
        assert calls["n"] == 2  # retry_max=2 -> 2 total attempts

    def test_get_client_creates_real_client(self):
        ch = DingTalkChannel(
            webhook="https://x.com",
            delivery=DeliveryConfig(retry_max=1),
            limiter=TokenBucket(10, 100),
        )
        client = ch._get_client()
        assert client is not None
        ch.close()
