"""
Shared fakes for the P4 "httpx first" tests: a real Fetcher over httpx.MockTransport that serves recorded pages, and a fake
Chromium renderer. Nothing here touches the network or a browser.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import Future
from pathlib import Path
from urllib.parse import unquote

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rag.live.browser import RenderResult  # noqa: E402
from rag.live.fetcher import Fetcher  # noqa: E402
from rag.live.ratelimit import RateLimiter  # noqa: E402


def page_response(body: bytes, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=body, headers={"content-type": "text/html; charset=utf-8"})


def static_fetcher(pages: dict[str, bytes], overrides: dict | None = None, limiter: RateLimiter | None = None,
                   log: list | None = None) -> Fetcher:
    """A Fetcher whose 'network' serves `pages` (url -> HTML bytes). `overrides` (url -> callable(request) -> Response, or an
    exception to raise) replace a page. Unknown URLs are 404. `log` collects (monotonic time, url) of every request."""
    by_url = {unquote(u): b for u, b in pages.items()}
    over = {unquote(u): f for u, f in (overrides or {}).items()}

    def handler(req: httpx.Request) -> httpx.Response:
        url = unquote(str(req.url))
        if log is not None:
            log.append((time.monotonic(), url))
        if url in over:
            o = over[url]
            if isinstance(o, BaseException):
                raise o
            return o(req)
        if url in by_url:
            return page_response(by_url[url])
        return httpx.Response(404)

    return Fetcher(limiter=limiter or RateLimiter(sleep=lambda s: None), transport=httpx.MockTransport(handler),
                   sleep=lambda s: None)


class FakeRender:
    """Stands in for BrowserOwner.render: returns an already-resolved Future. Records every call."""

    def __init__(self, pages: dict[str, bytes], overrides: dict | None = None, seconds: float = 3.0):
        self.pages = {unquote(u): b for u, b in pages.items()}
        self.overrides = {unquote(u): f for u, f in (overrides or {}).items()}
        self.seconds = seconds
        self.calls: list[str] = []

    def __call__(self, url: str) -> "Future[RenderResult]":
        self.calls.append(unquote(url))
        fut: Future = Future()
        key = unquote(url)
        if key in self.overrides:
            fut.set_result(self.overrides[key](url))
        elif key in self.pages:
            fut.set_result(RenderResult(url, ok=True, html=self.pages[key], status=200, elapsed=self.seconds,
                                        requests=40, requests_nccu=30))
        else:
            fut.set_result(RenderResult(url, error="http_4xx", status=404, detail="HTTP 404"))
        return fut


JS_SHELL = ("<html><body><div class='item-page'>國立政治大學國際合作事務處Office of International Cooperation, "
            "National Chengchi University</div></body></html>").encode()
