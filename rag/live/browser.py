"""
rag/live/browser.py
The browser-owner thread (docs/phase_j_live_fetch_plan.md, P4).

Playwright's SYNC API objects only work in the thread that created them (P4 step 0, T2: using a page from another
thread raises "Cannot switch to a different thread"), while LangGraph runs our sync nodes on whatever pool thread is
free. So ONE dedicated thread owns Chromium; any thread calls `render(url)` and gets a `Future` back -- like a
restaurant ticket: returned at once, redeemed later with `.result()` or picked up in completion order with
`concurrent.futures.as_completed`. Requests are served one at a time, in the order they arrive.

Lifecycle (bound to the process): the thread and the browser start on the first request (never at import or startup),
Chromium is closed after `idle_seconds` without work and restarted by the next request, `shutdown()` is registered with
atexit, and a crashed browser is restarted once per request. Failure is data: a request never raises, its Future
resolves to a RenderResult with `ok=False` and an error code (`start_failed`, `render_error`, `crashed`, `closed`).

The thing that actually drives Chromium is a `Backend` (swappable: tests use a fake, so none of this logic needs a
real browser). P4.5 (simultaneous crawling) can replace the loop with an asyncio one inside this same thread without
changing the `render()` signature.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable, ContextManager, Protocol

from rag.live import config

log = logging.getLogger("rag.live")


@dataclass
class RenderResult:
    url: str
    ok: bool = False
    html: bytes = b""
    status: int = 0
    error: str = ""            # start_failed|render_error|crashed|closed|<backend-specific>
    detail: str = ""
    elapsed: float = 0.0
    requests: int = 0          # HTTP requests the page made (the page itself + everything it loaded); passive count
    requests_nccu: int = 0     # ...of which went to *.nccu.edu.tw


class BrowserCrashed(Exception):
    """Raised by a backend when the browser itself died (not the page's fault) -> restart and retry once."""


class Backend(Protocol):
    def start(self) -> None: ...
    def render(self, url: str) -> RenderResult: ...
    def stop(self) -> None: ...


_CRASH_MARKERS = ("Target closed", "has been closed", "Browser closed", "Connection closed", "Target page, context or browser")


class PlaywrightBackend:
    """Real Chromium. All methods must be called from the owner thread.

    `render` is what fetch_office_contacts.py did for every staff page: open the URL, wait for `load`, wait a fixed
    settle time for late JS-injected content, take the DOM. (Not `networkidle`: tsc/cids.nccu.edu.tw never go idle.)
    Each render uses a fresh browser context, so cookies and storage never leak from one page to the next.
    """

    def __init__(self, settle_ms: int | None = None, nav_timeout_ms: int | None = None,
                 allow: Callable[[str], bool] | None = None, subresource_allow: Callable[[str], bool] | None = None):
        from rag.live.allowlist import is_allowed
        self.settle_ms = config.RENDER_SETTLE_MS if settle_ms is None else settle_ms
        self.nav_timeout_ms = config.RENDER_NAV_TIMEOUT_MS if nav_timeout_ms is None else nav_timeout_ms
        self._allow = allow or is_allowed                 # applied to the URL asked for and to wherever we end up
        self._sub_allow = subresource_allow               # None in production (pages load fonts/analytics as in P0);
        self._pw = None                                   # tests pass one to keep every request on localhost
        self.browser = None

    def start(self) -> None:
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            self.browser = self._pw.chromium.launch(headless=True)
        except BaseException:
            self._pw.stop()
            self._pw = None
            raise

    def render(self, url: str) -> RenderResult:
        from playwright.sync_api import Error as PWError, TimeoutError as PWTimeout
        t0 = time.monotonic()
        if not self._allow(url):
            return RenderResult(url, error="blocked_host", detail="not an http(s) *.nccu.edu.tw URL")
        if self.browser is None or not self.browser.is_connected():
            raise BrowserCrashed("browser is not connected")
        ctx = None
        try:
            ctx = self.browser.new_context()
            if self._sub_allow is not None:
                ctx.route("**/*", lambda route: route.continue_() if self._sub_allow(route.request.url) else route.abort())
            page = ctx.new_page()
            seen = {"all": 0, "nccu": 0}

            def count(req) -> None:                       # passive: only counts what the page itself asks for
                seen["all"] += 1
                seen["nccu"] += int(self._is_nccu(req.url))
            page.on("request", count)
            resp = page.goto(url, timeout=self.nav_timeout_ms, wait_until="load")
            if self.settle_ms:
                page.wait_for_timeout(self.settle_ms)
            final = page.url
            if not self._allow(final):
                return RenderResult(url, error="redirect_offsite", detail=final, elapsed=time.monotonic() - t0)
            status = resp.status if resp else 0
            if status >= 400:
                return RenderResult(url, status=status, error="http_5xx" if status >= 500 else "http_4xx",
                                    detail=f"HTTP {status}", elapsed=time.monotonic() - t0)
            # page.content() is a Unicode string; we hand it on as UTF-8 bytes. A page with no <meta charset> (or one that
            # still declares big5) would make the extractor's encoding sniffing guess wrong and garble Chinese text, so
            # the bytes carry a UTF-8 BOM, which takes priority over any declared or guessed encoding.
            return RenderResult(url, ok=True, html=b"\xef\xbb\xbf" + page.content().encode("utf-8"), status=status,
                                elapsed=time.monotonic() - t0, requests=seen["all"], requests_nccu=seen["nccu"])
        except PWTimeout as e:
            return RenderResult(url, error="timeout", detail=str(e).splitlines()[0][:160], elapsed=time.monotonic() - t0)
        except PWError as e:
            msg = str(e)
            if any(m in msg for m in _CRASH_MARKERS):
                raise BrowserCrashed(msg.splitlines()[0][:160]) from e
            return RenderResult(url, error="network", detail=msg.splitlines()[0][:160], elapsed=time.monotonic() - t0)
        finally:
            if ctx is not None:
                try:
                    ctx.close()
                except Exception:                           # noqa: BLE001 -- a dead context must not mask the result
                    pass

    @staticmethod
    def _is_nccu(url: str) -> bool:
        from urllib.parse import urlsplit
        host = (urlsplit(url).hostname or "").lower()
        return host == config.ALLOWED_DOMAIN or host.endswith("." + config.ALLOWED_DOMAIN)

    def stop(self) -> None:
        try:
            if self.browser is not None:
                self.browser.close()
        finally:
            self.browser = None
            if self._pw is not None:
                self._pw.stop()
                self._pw = None

    @property
    def running(self) -> bool:
        return self.browser is not None and self.browser.is_connected()


_STOP = object()


class BrowserOwner:
    def __init__(self, backend_factory: Callable[[], Backend] = PlaywrightBackend,
                 idle_seconds: float | None = None, name: str = "browser-owner",
                 around: Callable[[str], ContextManager] | None = None):
        self._factory = backend_factory
        self._around = around          # url -> context manager held while that page renders (rate limiting)
        self._idle = config.BROWSER_IDLE_SECONDS if idle_seconds is None else idle_seconds
        self._name = name
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._backend: Backend | None = None          # touched only by the owner thread
        self.thread_ident: int | None = None

    # --- public -------------------------------------------------------------------------------------------------
    def render(self, url: str) -> "Future[RenderResult]":
        fut: Future = Future()
        with self._lock:
            if self._closed:
                fut.set_result(RenderResult(url, error="closed", detail="browser owner is shut down"))
                return fut
            if self._thread is None:                    # lazy: the first request starts the thread
                self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
                self._thread.start()
            self._q.put((url, fut))
        return fut

    def shutdown(self, timeout: float = 30.0) -> None:
        """Idempotent. Pending requests resolve with error='closed'; Chromium is closed."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread
            if thread is not None:
                self._q.put(_STOP)
        if thread is not None:
            thread.join(timeout)

    close = shutdown

    # --- owner thread -------------------------------------------------------------------------------------------
    def _run(self) -> None:
        self.thread_ident = threading.get_ident()
        try:
            while True:
                try:
                    item = self._q.get(timeout=self._idle if self._backend is not None else None)
                except queue.Empty:                     # idle long enough: give the memory back
                    log.info("browser idle for %.0fs; closing Chromium", self._idle)
                    self._stop_backend()
                    continue
                if item is _STOP:
                    break
                url, fut = item
                if fut.set_running_or_notify_cancel():
                    fut.set_result(self._serve(url))
        finally:
            self._stop_backend()
            self._drain_closed()

    def _serve(self, url: str) -> RenderResult:
        t0 = time.monotonic()
        for attempt in (1, 2):                          # a crash is not the page's fault: one restart, one retry
            if self._backend is None and not self._start_backend():
                return RenderResult(url, error="start_failed", detail=self._last_start_error,
                                    elapsed=time.monotonic() - t0)
            try:
                with (self._around(url) if self._around else contextlib.nullcontext()):
                    res = self._backend.render(url)
                res.elapsed = res.elapsed or (time.monotonic() - t0)
                return res
            except BrowserCrashed as e:
                log.warning("browser crashed on %s (attempt %d): %s", url, attempt, e)
                self._stop_backend()
                if attempt == 2:
                    return RenderResult(url, error="crashed", detail=str(e)[:200], elapsed=time.monotonic() - t0)
            except Exception as e:                      # noqa: BLE001 -- the page's problem, keep the browser
                return RenderResult(url, error="render_error", detail=f"{type(e).__name__}: {e}"[:200],
                                    elapsed=time.monotonic() - t0)
        return RenderResult(url, error="crashed")       # unreachable; keeps the type checker calm

    _last_start_error = ""

    def _start_backend(self) -> bool:
        try:
            backend = self._factory()
            backend.start()
        except Exception as e:                          # noqa: BLE001
            self._last_start_error = f"{type(e).__name__}: {e}"[:200]
            log.warning("browser failed to start: %s", self._last_start_error)
            self._backend = None
            return False
        self._backend = backend
        return True

    def _stop_backend(self) -> None:
        backend, self._backend = self._backend, None
        if backend is not None:
            try:
                backend.stop()
            except Exception as e:                      # noqa: BLE001 -- closing must never take the thread down
                log.warning("browser stop failed: %s: %s", type(e).__name__, e)

    def _drain_closed(self) -> None:
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                return
            if item is not _STOP:
                url, fut = item
                if fut.set_running_or_notify_cancel():
                    fut.set_result(RenderResult(url, error="closed", detail="shut down before it ran"))


# --- process-wide instance ---------------------------------------------------------------------------------------
_owner: BrowserOwner | None = None
_owner_lock = threading.Lock()


def _shared_limiter_slot(url: str):
    """Rate-limit Chromium page loads with the SAME limiter the httpx fetcher uses, so the per-host gap (osa: 10 s) holds
    across both kinds of request."""
    from rag.live.allowlist import host_of
    from rag.live.hook import get_fetcher
    return get_fetcher().limiter.slot(host_of(url))


def get_owner() -> BrowserOwner:
    global _owner
    with _owner_lock:
        if _owner is None or _owner._closed:
            _owner = BrowserOwner(around=_shared_limiter_slot)
            atexit.register(_owner.shutdown)
        return _owner
