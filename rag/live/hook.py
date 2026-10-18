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
import time

from rag.live import config
from rag.live.allowlist import is_allowed
from rag.live.cache import LiveCache
from rag.live.clock import taipei_minute
from rag.live.config import live_enabled
from rag.live.fetcher import Fetcher
from rag.live.ledger import (DISCONTINUED, LIVE_CHANGED, LIVE_INCOMPLETE, LIVE_NEW, LIVE_SAME, SNAPSHOT, SNAPSHOT_FALLBACK, make_marker,
                             sanitize)
from rag.live import resolve as R

log = logging.getLogger("rag.live")

_fetcher: Fetcher | None = None
_fetcher_lock = threading.Lock()

_STATE_MAP = {R.LIVE_SAME: LIVE_SAME, R.LIVE_CHANGED: LIVE_CHANGED, R.LIVE_ONLY: LIVE_NEW,
              R.LIVE_INCOMPLETE: LIVE_INCOMPLETE, R.SNAPSHOT_FALLBACK: SNAPSHOT_FALLBACK}


def _cache_info(from_cache: bool, fetched_at: float) -> tuple[bool, int | None]:
    """(came from the side cache, minutes since it was fetched). The marker says so, so the answer can tell "checked 3 minutes ago"
    from "checked for this question"."""
    if not from_cache:
        return False, None
    return True, max(0, int((time.time() - fetched_at) // 60)) if fetched_at else None


def _snapshot_marked(page: dict, url: str, title_key: str, kind: str) -> dict:
    """A question that explicitly turned live OFF (live=False, the front end's switch) still records what it read: the page comes back
    unchanged, plus a ledger line with state "snapshot" so the sources panel can list it as database data. live=None (the CLI default, or
    LIVE_FETCH unset) returns the page untouched, byte-for-byte as before P8."""
    if "error" in page:
        return page
    out = dict(page)
    out["live_marker"] = make_marker(url if kind == "form" else (page.get("url") or url), SNAPSHOT, "", config.SNAPSHOT_ASOF, kind=kind, title=page.get(title_key) or "")
    out["live_state"] = SNAPSHOT
    return out


def get_fetcher() -> Fetcher:
    global _fetcher
    with _fetcher_lock:
        if _fetcher is None:
            _fetcher = Fetcher(cache=LiveCache())
        return _fetcher


def apply_page(url: str, snapshot_page: dict, live: bool | None = None) -> dict:
    """`snapshot_page` is get_page()'s result: a page dict, or {"error": ...} when the URL is not in the corpus.
    `live` is this question's choice (AgentState["live"]); None = decided by LIVE_FETCH alone (config.live_enabled)."""
    if not live_enabled(live):
        return _snapshot_marked(snapshot_page, url, "title", "page") if live is False else snapshot_page
    snap_found = "error" not in snapshot_page
    target = snapshot_page.get("url") or url          # the stored URL when get_page matched by prefix
    if not is_allowed(target):
        return snapshot_page
    live = get_fetcher().fetch(target, kind="page")
    log.info("live fetch %s -> %s in %.2fs (attempts=%d, cache=%s)", target, "ok" if live.ok else live.error, live.elapsed, live.attempts, live.from_cache)
    res = R.resolve(snapshot_page.get("text") if snap_found else None, live)

    if not snap_found and res.state == R.SNAPSHOT_FALLBACK:
        return snapshot_page                           # not in the corpus and not reachable live: plain "not found"
    page = dict(snapshot_page) if snap_found else {"url": live.final_url or target, "title": "", "subdomain": ""}
    page["text"] = sanitize(res.text)
    state = _STATE_MAP[res.state]
    checked = taipei_minute(live.fetched_at or None) if live.ok else taipei_minute()
    cached, age = _cache_info(live.from_cache, live.fetched_at)
    page["live_marker"] = make_marker(target, state, checked, config.SNAPSHOT_ASOF, res.tls_unverified, cached=cached, age_min=age,
                                      title=page.get("title") or "")
    page["live_state"] = state
    if res.comparison and not res.comparison.same:
        log.info("live diff %s: %s", target, res.comparison.summary())
    if not live.ok:
        log.warning("live fetch failed %s: %s %s", target, live.error, live.detail)
    return page


def apply_form(form_id: str, snapshot_form: dict, live: bool | None = None) -> dict:
    """`snapshot_form` is agent_tools.get_form()'s result (or {"error": ...}). Same decision rule as pages:
    unchanged -> snapshot text, changed -> live text, live failed -> snapshot + disclosure, withdrawn -> no text."""
    if not live_enabled(live):
        form = snapshot_form() if callable(snapshot_form) else snapshot_form
        if live is False:
            from rag.live.forms import link_url_for
            return _snapshot_marked(form, link_url_for(form_id), "form_title", "form")
        return form
    from rag.live.forms import fetch_form, link_url_for
    link = link_url_for(form_id)
    live = fetch_form(form_id, get_fetcher())
    # `snapshot_form` may be a callable (the prefetch passes one): the live fetch above has already started without waiting for the
    # local snapshot lookup, which only has to be ready by the time the two are compared.
    snapshot_form = snapshot_form() if callable(snapshot_form) else snapshot_form
    snap_found = "error" not in snapshot_form
    log.info("live form %s -> %s in %.2fs (%d requests, cache=%s)", form_id, "ok" if live.ok else live.error,
             live.elapsed, live.requests, live.from_cache)
    checked = taipei_minute(live.fetched_at or None) if live.ok else taipei_minute()

    def marked(page: dict, state: str) -> dict:
        cached, age = _cache_info(live.from_cache, live.fetched_at)
        page["live_marker"] = make_marker(link, state, checked, config.SNAPSHOT_ASOF, kind="form", cached=cached, age_min=age,
                                          title=page.get("form_title") or "")
        page["live_state"] = state
        return page

    if live.ok and live.discontinued:
        base = dict(snapshot_form) if snap_found else {"form_id": form_id, "url": link}
        base.update(text="", form_title=live.title or base.get("form_title", ""), discontinued=True)
        return marked(base, DISCONTINUED)
    from rag.live.fetcher import LiveResult
    res = R.resolve(snapshot_form.get("text") if snap_found else None,
                    LiveResult(link, ok=live.ok, text=live.text, error=live.error, detail=live.detail))
    if not snap_found and res.state == R.SNAPSHOT_FALLBACK:
        return snapshot_form                              # unknown form, unreachable: plain "not found"
    page = dict(snapshot_form) if snap_found else {"form_id": form_id, "url": link, "form_description": ""}
    page["text"] = sanitize(res.text)
    if live.ok and res.state != R.LIVE_INCOMPLETE:
        page["form_title"] = live.title or page.get("form_title", "")
        page["form_unit"] = live.unit or page.get("form_unit", "")
    if res.comparison and not res.comparison.same:
        log.info("live form diff %s: %s", form_id, res.comparison.summary())
    return marked(page, _STATE_MAP[res.state])
