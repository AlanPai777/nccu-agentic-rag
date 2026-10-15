"""
rag/live/fetcher.py
Live HTTP fetch of one nccu.edu.tw URL -> extracted text (§5.1-5.6), using the same extractors that
built the snapshot (rag/preprocess.py) so live-vs-snapshot differences are real, not extractor drift.

Failure is data, not an exception: fetch() always returns a LiveResult, with `error` set to a short
code when the page could not be obtained. Callers fall back to the snapshot and say so.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from rag.live import config
from rag.live.allowlist import host_of, is_allowed
from rag.live.cache import CacheRow, LiveCache
from rag.live.ratelimit import RateLimiter

log = logging.getLogger("rag.live")


@dataclass
class LiveResult:
    url: str
    ok: bool = False
    final_url: str = ""
    status: int = 0
    text: str = ""
    error: str = ""            # blocked_host|breaker_open|timeout|network|tls|http_4xx|http_5xx|redirect_offsite|
                               # too_many_redirects|cloudflare|soft_404|empty|too_large
    detail: str = ""
    raw_hash: str = ""
    elapsed: float = 0.0
    fetched_at: float = 0.0    # unix time the body was actually received (cache hits keep the original)
    attempts: int = 0
    tls_unverified: bool = False
    from_cache: bool = False
    redirects: list[str] = field(default_factory=list)
    body: bytes = b""           # only filled for raw=True fetches


def _sha(b: bytes | str) -> str:
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode("utf-8")).hexdigest()[:16]


def _retry_after(resp: httpx.Response) -> float | None:
    v = resp.headers.get("retry-after", "")
    try:
        return min(float(v), config.RETRY_AFTER_CAP) if v.strip() else None
    except ValueError:
        return None   # HTTP-date form: ignore, backoff applies


class Fetcher:
    def __init__(self, limiter: RateLimiter | None = None, cache: LiveCache | None = None,
                 transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        self.limiter = limiter or RateLimiter()
        self.cache = cache
        self._transport = transport          # tests inject httpx.MockTransport
        self._sleep = sleep
        self._clients: dict[tuple[bool, bool], httpx.Client] = {}
        self._clients_lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}
        self._results: dict[str, LiveResult] = {}
        self._flight_lock = threading.Lock()

    # --- plumbing ----------------------------------------------------------------------------
    def _make_client(self, host: str) -> httpx.Client:
        verify = host not in config.INSECURE_TLS_HOSTS
        legacy = host in config.LEGACY_RENEGOTIATION_HOSTS
        v: object = verify
        if self._transport is None and verify and legacy:
            import ssl
            ctx = ssl.create_default_context()
            ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
            v = ctx
        return httpx.Client(headers={"User-Agent": config.USER_AGENT}, follow_redirects=False,
                            timeout=httpx.Timeout(config.REQUEST_TIMEOUT), verify=v, transport=self._transport)

    def _client(self, host: str) -> httpx.Client:
        """Shared client (and cookie jar) per TLS profile. Fine for stateless pages."""
        key = (host not in config.INSECURE_TLS_HOSTS, host in config.LEGACY_RENEGOTIATION_HOSTS)
        with self._clients_lock:
            if key not in self._clients:
                self._clients[key] = self._make_client(host)
            return self._clients[key]

    def new_session(self, host: str) -> httpx.Client:
        """A private client with its own cookie jar, for server-side-session flows (moltke forms: the last
        request of the 5-step chain has no form id in its URL, the session decides which form you get).
        The caller closes it."""
        return self._make_client(host)

    def close(self) -> None:
        for c in self._clients.values():
            c.close()

    # --- public ------------------------------------------------------------------------------
    def fetch(self, url: str, kind: str = "page", use_cache: bool = True,
              client: httpx.Client | None = None, raw: bool = False) -> LiveResult:
        """Singleflight: concurrent callers for the same URL share one live request."""
        with self._flight_lock:
            ev = self._inflight.get(url)
            leader = ev is None
            if leader:
                ev = self._inflight[url] = threading.Event()
        if not leader:
            ev.wait()
            return self._results.get(url) or LiveResult(url, error="network", detail="leader vanished")
        try:
            res = self._fetch_once(url, kind, use_cache, client, raw)
        except Exception as e:     # never let a bug here take down a query
            log.exception("live fetch crashed: %s", url)
            res = LiveResult(url, error="network", detail=f"internal: {type(e).__name__}: {e}")
        with self._flight_lock:
            self._results[url] = res
            self._inflight.pop(url, None)
        ev.set()
        return res

    def fetch_many(self, urls: list[str], kind: str = "page", workers: int | None = None) -> dict[str, LiveResult]:
        from concurrent.futures import ThreadPoolExecutor
        urls = list(dict.fromkeys(urls))
        with ThreadPoolExecutor(max_workers=workers or max(1, min(len(urls), 8))) as ex:
            return dict(zip(urls, ex.map(lambda u: self.fetch(u, kind), urls)))

    # --- core --------------------------------------------------------------------------------
    def _fetch_once(self, url: str, kind: str, use_cache: bool, client, raw: bool) -> LiveResult:
        t0 = time.monotonic()
        if not is_allowed(url):
            return LiveResult(url, error="blocked_host", detail="not an http(s) *.nccu.edu.tw URL")
        if use_cache and self.cache and not raw:
            row = self.cache.get(url)
            if row:
                return LiveResult(url, True, row.final_url, row.status, row.text, raw_hash=row.raw_hash,
                                  fetched_at=row.fetched_at, tls_unverified=row.tls_unverified, from_cache=True)
        host = host_of(url)
        res = LiveResult(url)
        for attempt in range(config.MAX_RETRIES + 1):
            res.attempts = attempt + 1
            if self.limiter.breaker_open(host):
                res.error, res.detail = "breaker_open", f"{host} paused after repeated failures"
                break
            res = self._attempt(url, host, res, client, raw)
            if res.ok:
                break
            retryable = res.error in ("timeout", "network", "http_5xx", "http_429")
            if not retryable or attempt == config.MAX_RETRIES:
                break
            self._sleep(config.BACKOFF_BASE * 2 ** attempt)
        res.elapsed = time.monotonic() - t0
        if res.ok and self.cache and not raw:
            self.cache.put(CacheRow(url, kind, res.final_url, res.fetched_at, res.status, res.raw_hash,
                                    _sha(res.text), res.text, None, res.tls_unverified))
        return res

    def _attempt(self, url: str, host: str, res: LiveResult, client, raw: bool) -> LiveResult:
        res.error = res.detail = ""
        res.redirects = []
        cur = url
        for _ in range(config.MAX_REDIRECTS + 1):
            h = host_of(cur)
            if not is_allowed(cur):
                res.error, res.detail = "redirect_offsite", cur
                return res
            tls_off = h in config.INSECURE_TLS_HOSTS
            if tls_off:
                log.warning("TLS verification disabled for %s (INSECURE_TLS_HOSTS)", h)
                res.tls_unverified = True
            try:
                with self.limiter.slot(h):
                    r = (client or self._client(h)).get(cur)
            except httpx.TimeoutException as e:
                self.limiter.record_failure(h)
                res.error, res.detail = "timeout", type(e).__name__
                return res
            except httpx.HTTPError as e:
                self.limiter.record_failure(h)
                is_tls = "CERTIFICATE" in str(e).upper() or "SSL" in str(e).upper()
                res.error, res.detail = ("tls" if is_tls else "network"), f"{type(e).__name__}: {e}"[:200]
                return res
            res.status = r.status_code
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                nxt = str(httpx.URL(cur).join(r.headers["location"]))
                res.redirects.append(nxt)
                cur = nxt
                continue
            return self._finish(r, cur, h, res, raw)
        res.error, res.detail = "too_many_redirects", cur
        return res

    def _finish(self, r: httpx.Response, final_url: str, host: str, res: LiveResult, raw: bool = False) -> LiveResult:
        res.final_url = final_url
        if r.status_code in (429, 503):
            ra = _retry_after(r)
            self.limiter.penalize(host, ra if ra is not None else config.BACKOFF_BASE)
            self.limiter.record_failure(host)
            res.error, res.detail = "http_429" if r.status_code == 429 else "http_5xx", f"HTTP {r.status_code}"
            return res
        if r.status_code >= 500:
            self.limiter.record_failure(host)
            res.error, res.detail = "http_5xx", f"HTTP {r.status_code}"
            return res
        if r.status_code >= 400:
            res.error, res.detail = "http_4xx", f"HTTP {r.status_code}"
            return res
        self.limiter.record_success(host)
        body = r.content
        if len(body) > config.MAX_BODY_BYTES:
            res.error = "too_large"
            return res
        if "/ErrorPages/" in final_url or "/errorpages/" in final_url.lower():
            res.error, res.detail = "soft_404", final_url
            return res
        res.raw_hash = _sha(body)
        if raw:                       # caller parses the markup itself (e.g. moltke's goFile tokens)
            res.body, res.ok = body, bool(body)
            res.error = "" if body else "empty"
            res.fetched_at = self.cache.now() if self.cache else time.time()
            return res
        ctype = r.headers.get("content-type", "").lower()
        if "pdf" in ctype or final_url.lower().split("?")[0].endswith(".pdf"):
            text = self._pdf_text(body)
        else:
            from rag.preprocess import extract_html_bytes, is_cloudflare_page
            if is_cloudflare_page(body):
                res.error = "cloudflare"
                return res
            text = extract_html_bytes(body, final_url)
            # With no usable content the extractor falls back to a title made from the URL's last
            # path segment; that is "nothing extracted", not content.
            if text.strip() == Path(final_url.rstrip("/").split("/")[-1]).stem or "Blank Component" in text:
                text = ""
        if not text.strip():
            res.error = "empty"
            return res
        res.text, res.ok = text, True
        res.fetched_at = self.cache.now() if self.cache else time.time()
        return res

    @staticmethod
    def _pdf_text(body: bytes) -> str:
        from rag.preprocess import extract_pdf
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(body)
            p = Path(f.name)
        try:
            return extract_pdf(p)
        finally:
            p.unlink(missing_ok=True)
