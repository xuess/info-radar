"""Collector fetcher: httpx fetch with ETag/Last-Modified incremental,
retry, timeout, UA. Returns raw bytes + updated cache headers.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..config import CollectConfig


@dataclass(frozen=True)
class FetchResult:
    """Result of fetching a single feed URL."""

    content: bytes
    status: int
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False
    url: str = ""


class FetchError(Exception):
    """Raised when a feed cannot be fetched after retries."""


def _headers(cfg: CollectConfig, etag: str | None, last_modified: str | None) -> dict[str, str]:
    h = {"User-Agent": cfg.user_agent, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}
    if etag:
        h["If-None-Match"] = etag
    if last_modified:
        h["If-Modified-Since"] = last_modified
    return h


def fetch(
    url: str,
    cfg: CollectConfig,
    etag: str | None = None,
    last_modified: str | None = None,
) -> FetchResult:
    """Fetch a feed URL with incremental headers and retry.

    - 200 -> content + new etag/last_modified
    - 304 -> not_modified, empty content
    - 429 -> retry once after backoff
    - 5xx/timeout -> exponential backoff up to max_retries
    - other 4xx -> FetchError (caller marks source disabled)
    """
    last_exc: Exception | None = None
    backoff = 1.0

    for attempt in range(cfg.max_retries + 1):
        try:
            with httpx.Client(
                timeout=cfg.timeout,
                follow_redirects=True,
            ) as client:
                resp = client.get(url, headers=_headers(cfg, etag, last_modified))

            if resp.status_code == 304:
                return FetchResult(
                    content=b"",
                    status=304,
                    etag=etag,
                    last_modified=last_modified,
                    not_modified=True,
                    url=url,
                )
            if resp.status_code == 200:
                return FetchResult(
                    content=resp.content,
                    status=200,
                    etag=resp.headers.get("ETag"),
                    last_modified=resp.headers.get("Last-Modified"),
                    url=url,
                )
            if resp.status_code == 429 and attempt < cfg.max_retries:
                # Rate limited: back off and retry
                import time

                time.sleep(min(backoff * 2, 60))
                backoff *= 2
                continue
            if 500 <= resp.status_code < 600 and attempt < cfg.max_retries:
                import time

                time.sleep(backoff)
                backoff *= 2
                continue
            # Non-retryable status
            raise FetchError(
                f"fetch {url} failed: HTTP {resp.status_code}"
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            if attempt >= cfg.max_retries:
                raise FetchError(f"fetch {url} timed out after {cfg.max_retries} retries: {exc}") from exc
            import time

            time.sleep(backoff)
            backoff *= 2
            continue

    # Should not reach here, but guard
    raise FetchError(f"fetch {url} exhausted retries: {last_exc}")
