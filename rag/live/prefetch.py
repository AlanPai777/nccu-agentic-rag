"""
rag/live/prefetch.py
Prefetch (docs/phase_j_live_fetch_plan.md, P5): start the live reads a chain will need BEFORE the chain asks for them.

Today the live reads are a relay race -- each leg needs the previous leg's text to know what to fetch:
    read the page (live check) -> its form ids -> fetch the forms -> their offices -> fetch the staff pages
The snapshot holds an older copy of every one of those texts, so the same questions can be answered from it immediately
("which forms does this page list?" "which offices do those forms name?"), with the very same functions, and the live fetches
for those answers can start at once, while the real chain is still on its first leg. Nothing is guessed by a model: it is the
usual steps run on the snapshot text first. If the live site turns out to differ (a new form, another office), the real chain
simply fetches what the prefetch did not cover.

How the real chain uses it: get_form_tool and fetch_contact_pages ask the store first. A result that the prefetch finished (or
is still producing) is used -- an in-flight one is waited for, never duplicated. Anything not in the store, expired, or failed
is simply done the normal way. Only entries the prefetch itself started are stored, so with LIVE_PREFETCH off the store is
empty and behaviour is exactly what it was.

Off by default (LIVE_PREFETCH=on, and only together with LIVE_FETCH=on). No budget cap of its own: it fetches what the real chain
would have fetched anyway (user decision 2026-10-16); the chain's own lack of caps is a known, separately recorded trade-off.
"""

from __future__ import annotations

import atexit
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from rag.live import config

log = logging.getLogger("rag.live")


class PrefetchStore:
    """Futures of prefetch-started work, by kind ("snap" | "form" | "contact") and key, each valid for `ttl` seconds."""

    def __init__(self, ttl: float | None = None, clock=time.monotonic, workers: int | None = None):
        self._ttl = config.PREFETCH_TTL_SECONDS if ttl is None else ttl
        self._clock = clock
        self._workers = workers or config.PREFETCH_WORKERS
        self._lock = threading.Lock()
        self._items: dict[tuple[str, str], tuple[float, Future]] = {}
        self._pages: dict[str, float] = {}
        self._executor: ThreadPoolExecutor | None = None

    # --- running work in the background ------------------------------------------------------------------------
    def _pool(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=self._workers, thread_name_prefix="prefetch")
                atexit.register(self.shutdown)
            return self._executor

    def submit(self, kind: str, key: str, fn: Callable[[], Any]) -> Future:
        """Run fn in the background and remember its Future. A fresh entry for the same key is reused, not restarted."""
        with self._lock:
            hit = self._fresh(kind, key)
            if hit is not None:
                return hit
        fut = self._pool().submit(fn)
        with self._lock:
            self._items[(kind, key)] = (self._clock(), fut)
        return fut

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            ex, self._executor = self._executor, None
        if ex is not None:
            ex.shutdown(wait=wait, cancel_futures=not wait)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._pages.clear()

    # --- using it from the real chain ---------------------------------------------------------------------------
    def _fresh(self, kind: str, key: str) -> Future | None:
        entry = self._items.get((kind, key))
        if entry is None:
            return None
        started, fut = entry
        if self._clock() - started > self._ttl:
            del self._items[(kind, key)]
            return None
        return fut

    def reuse(self, kind: str, key: str, make: Callable[[], Any]) -> Any:
        """The prefetched result if there is one (waiting for it if it is still running), otherwise make(). A prefetch that
        failed counts as no prefetch. make() is never stored: only prefetch-started work is."""
        with self._lock:
            fut = self._fresh(kind, key)
        if fut is not None:
            try:
                return fut.result()
            except Exception as e:                      # noqa: BLE001 -- fall back to doing it the normal way
                log.warning("prefetched %s %s failed (%s: %s); doing it normally", kind, key, type(e).__name__, e)
        return make()

    def form_snapshot(self, form_id: str, make):
        return self.reuse("snap", form_id, make)

    def form_live(self, form_id: str, make):
        return self.reuse("form", form_id, make)

    def contact(self, url: str, make):
        return self.reuse("contact", url, make)

    # --- one chain per page read ---------------------------------------------------------------------------------
    def claim_page(self, url: str) -> bool:
        """True the first time a page is seen within the ttl: one prefetch chain per page read, not per call."""
        with self._lock:
            t = self._pages.get(url)
            if t is not None and self._clock() - t <= self._ttl:
                return False
            self._pages[url] = self._clock()
            return True


_store: PrefetchStore | None = None
_store_lock = threading.Lock()


def get_store() -> PrefetchStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = PrefetchStore()
        return _store


class Deps:
    """The real functions the chain uses; tests replace them. Imports are inside the methods so importing this module is cheap and
    cannot form a cycle with contacts.py / the tools."""

    def extract_form_ids(self, text: str) -> list[str]:
        from rag.agent_tools import extract_form_ids
        return sorted(extract_form_ids(text))

    def form_snapshot(self, form_id: str) -> dict:
        from rag.agent_tools import get_form
        return get_form(form_id)

    def live_form(self, form_id: str, snapshot_provider) -> dict:
        from rag.live.hook import apply_form
        return apply_form(form_id, snapshot_provider, live=True)       # the chain only runs when this question is live

    def detect_offices(self, text: str) -> list[str]:
        from rag.agentic.logic.office_detection import _detect_offices
        return _detect_offices(text)

    def plan_pages(self, offices: list[str]):
        from rag.live.contacts import plan_pages
        return plan_pages(offices)

    def process_page(self, url: str, info: dict):
        from rag.live.contacts import _default_handler, default_backends, process_page
        fetch_static, render = default_backends()
        return process_page(url, info, fetch_static, render, _default_handler)


def maybe_start(page_url: str, snapshot_page: dict, store: PrefetchStore | None = None, deps: Deps | None = None,
                force: bool = False, live: bool | None = None) -> bool:
    """Called by get_page_tool right after the local snapshot read and BEFORE the live check. Returns True if a chain was started.
    Never raises and never blocks: everything runs in the background."""
    try:
        if not force and not (config.live_enabled(live) and config.prefetch_enabled()):
            return False
        if not isinstance(snapshot_page, dict) or "error" in snapshot_page:
            return False
        deps = deps or Deps()
        store = store or get_store()
        ids = deps.extract_form_ids(snapshot_page.get("text", ""))
        if not ids or not store.claim_page(page_url):
            return False
        store._pool().submit(_run_chain, page_url, ids, store, deps)
        return True
    except Exception as e:                              # noqa: BLE001 -- the prefetch must never hurt the real chain
        log.warning("prefetch not started: %s: %s", type(e).__name__, e)
        return False


def _run_chain(page_url: str, ids: list[str], store: PrefetchStore, deps: Deps) -> None:
    t0 = time.monotonic()
    try:
        snaps: dict[str, Future] = {}
        for fid in ids:
            snaps[fid] = store.submit("snap", fid, lambda fid=fid: deps.form_snapshot(fid))
            # the live fetch starts now; it only needs the snapshot at the moment the two are compared
            store.submit("form", fid, lambda fid=fid: deps.live_form(fid, lambda fid=fid: snaps[fid].result()))
        texts = []
        for fid, fut in snaps.items():
            try:
                f = fut.result()
                if "error" not in f:
                    texts.append(f"{f.get('form_title', '')}\n{f.get('text', '')}")
            except Exception as e:                      # noqa: BLE001
                log.warning("prefetch: snapshot of form %s failed: %s", fid, e)
        offices = deps.detect_offices("\n\n".join(texts)) if texts else []
        pages, _ = deps.plan_pages(offices) if offices else ({}, [])
        for url, info in pages.items():
            store.submit("contact", url, lambda url=url, info=info: deps.process_page(url, info))
        log.info("prefetch from %s: %d forms, offices=%s, %d staff pages started (%.1fs)", page_url, len(ids), offices,
                 len(pages), time.monotonic() - t0)
    except Exception as e:                              # noqa: BLE001
        log.warning("prefetch chain failed: %s: %s", type(e).__name__, e)
