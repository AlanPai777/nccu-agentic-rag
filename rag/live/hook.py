"""
rag/live/hook.py
The single place get_page_tool asks "should this page be confirmed live?" (docs/phase_j_live_fetch_plan.md §5.2).

  LIVE_FETCH=off (default): returns the snapshot dict untouched -> agent behaviour is exactly as before.
  LIVE_FETCH=on : fetch the live page (the snapshot was already read, in milliseconds), compare, and return
                  a page dict whose text is the snapshot when unchanged, the live text when changed, the snapshot
                  when the live fetch failed. The dict gains "live_marker" (a ledger line for the tool header).
"""

from __future__ import annotations

import logging
import threading

from rag.live import config
from rag.live.allowlist import is_allowed
from rag.live.cache import LiveCache
from rag.live.clock import taipei_minute
from rag.live.config import live_mode
from rag.live.fetcher import Fetcher
from rag.live.ledger import (LIVE_CHANGED, LIVE_INCOMPLETE, LIVE_NEW, LIVE_SAME, SNAPSHOT_FALLBACK, make_marker,
                             sanitize)
from rag.live import resolve as R

log = logging.getLogger("rag.live")

_fetcher: Fetcher | None = None
_fetcher_lock = threading.Lock()

_STATE_MAP = {R.LIVE_SAME: LIVE_SAME, R.LIVE_CHANGED: LIVE_CHANGED, R.LIVE_ONLY: LIVE_NEW,
              R.LIVE_INCOMPLETE: LIVE_INCOMPLETE, R.SNAPSHOT_FALLBACK: SNAPSHOT_FALLBACK}


def get_fetcher() -> Fetcher:
    global _fetcher
    with _fetcher_lock:
        if _fetcher is None:
            _fetcher = Fetcher(cache=LiveCache())
        return _fetcher


def apply_page(url: str, snapshot_page: dict) -> dict:
    """`snapshot_page` is get_page()'s result: a page dict, or {"error": ...} when the URL is not in the corpus."""
    if live_mode() == "off":
        return snapshot_page
    snap_found = "error" not in snapshot_page
    target = snapshot_page.get("url") or url          # the stored URL when get_page matched by prefix
    if not is_allowed(target):
        return snapshot_page
    live = get_fetcher().fetch(target, kind="page")
    res = R.resolve(snapshot_page.get("text") if snap_found else None, live)

    if not snap_found and res.state == R.SNAPSHOT_FALLBACK:
        return snapshot_page                           # not in the corpus and not reachable live: plain "not found"
    page = dict(snapshot_page) if snap_found else {"url": live.final_url or target, "title": "", "subdomain": ""}
    page["text"] = sanitize(res.text)
    state = _STATE_MAP[res.state]
    checked = taipei_minute(live.fetched_at or None) if live.ok else taipei_minute()
    page["live_marker"] = make_marker(target, state, checked, config.SNAPSHOT_ASOF, res.tls_unverified)
    page["live_state"] = state
    if res.comparison and not res.comparison.same:
        log.info("live diff %s: %s", target, res.comparison.summary())
    if not live.ok:
        log.warning("live fetch failed %s: %s %s", target, live.error, live.detail)
    return page
