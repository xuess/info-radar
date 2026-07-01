"""Tests for collector/fetcher.py — uses httpx MockTransport, no real network."""
from __future__ import annotations

import httpx
import pytest

from infodigest.collector.fetcher import FetchError, fetch
from infodigest.config import CollectConfig

URL = "https://feed.example.com/rss"


def _cfg(**kw) -> CollectConfig:
    defaults = dict(timeout=5.0, max_retries=2, user_agent="InfoDigest/test", respect_robots=False)
    defaults.update(kw)
    return CollectConfig(**defaults)


def _make_client_handler(status: int, body: bytes = b"<rss/>", headers: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers=headers or {})

    return handler


class TestFetchOk:
    def test_200_returns_content(self, monkeypatch):
        cfg = _cfg()
        captured = {}

        def transport_handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, content=b"<rss>ok</rss>", headers={"ETag": '"abc"'})


        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url, headers=None):
                req = httpx.Request("GET", url, headers=headers)
                return transport_handler(req)

        monkeypatch.setattr(httpx, "Client", FakeClient)
        result = fetch(URL, cfg)
        assert result.status == 200
        assert result.content == b"<rss>ok</rss>"
        assert result.etag == '"abc"'
        assert not result.not_modified
        # UA header sent
        assert captured["headers"]["user-agent"] == "InfoDigest/test"

    def test_etag_sent_on_200(self, monkeypatch):
        cfg = _cfg()
        captured = {}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url, headers=None):
                captured["headers"] = headers or {}
                return httpx.Response(200, content=b"x")

        monkeypatch.setattr(httpx, "Client", FakeClient)
        fetch(URL, cfg, etag='"prev"', last_modified="Mon, 01 Jul 2026 00:00:00 GMT")
        assert captured["headers"]["If-None-Match"] == '"prev"'
        assert "If-Modified-Since" in captured["headers"]

    def test_304_not_modified(self, monkeypatch):
        cfg = _cfg()

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url, headers=None):
                return httpx.Response(304)

        monkeypatch.setattr(httpx, "Client", FakeClient)
        result = fetch(URL, cfg, etag='"abc"')
        assert result.not_modified
        assert result.content == b""
        assert result.status == 304


class TestFetchErrors:
    def test_404_raises_fetch_error(self, monkeypatch):
        cfg = _cfg(max_retries=0)

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url, headers=None):
                return httpx.Response(404)

        monkeypatch.setattr(httpx, "Client", FakeClient)
        with pytest.raises(FetchError, match="HTTP 404"):
            fetch(URL, cfg)

    def test_500_retries_then_raises(self, monkeypatch):
        cfg = _cfg(max_retries=1)
        calls = {"n": 0}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url, headers=None):
                calls["n"] += 1
                return httpx.Response(500)

        # Patch time.sleep to avoid real delays
        import time

        monkeypatch.setattr(time, "sleep", lambda s: None)
        monkeypatch.setattr(httpx, "Client", FakeClient)
        with pytest.raises(FetchError, match="HTTP 500"):
            fetch(URL, cfg)
        assert calls["n"] == 2  # initial + 1 retry
