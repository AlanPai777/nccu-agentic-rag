"""
rag/live/contacts.py
Live staff pages for the offices contact_node found (docs/phase_j_live_fetch_plan.md, P4, "httpx 優先").

For each office: the office_contacts_index.jsonl record(s) say WHICH page lists its staff (the same lookup the snapshot
path does). Each such page is one task in a thread pool:

    httpx GET (rate-limited per host)  ->  text with the snapshot's own extractor  ->  compared with the index text
      -> escalation check A/B (rag/live/escalate.py)  -> parse the contacts (handler; may call an LLM for some layouts)
      -> escalation check C
      -> no escalation: the static result stands
      -> escalation:    Chromium renders the page (browser-owner thread), same compare/parse, and that result stands

Pages run side by side; the rate limiter makes osa.nccu.edu.tw's pages wait their 10 s turns without holding anything
up. One page's handler (parsing) runs while other pages are still being fetched. Offices with no index record are returned
in `uncovered`: they stay on the snapshot path and the answer says so.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from rag.live import config, events, ledger, resolve as R
from rag.live.clock import taipei_minute
from rag.live.compare import Comparison
from rag.live.extract import html_to_text
from rag.live.escalate import post_parse_reason, pre_parse_reason, static_similarity
from rag.live.fetcher import LiveResult

log = logging.getLogger("rag.live")

_STATE = {R.LIVE_SAME: ledger.LIVE_SAME, R.LIVE_CHANGED: ledger.LIVE_CHANGED, R.LIVE_ONLY: ledger.LIVE_NEW,
          R.LIVE_INCOMPLETE: ledger.LIVE_INCOMPLETE, R.SNAPSHOT_FALLBACK: ledger.SNAPSHOT_FALLBACK}


@dataclass
class PageOutcome:
    url: str
    offices: list[str]
    state: str                       # a ledger status: live_same|live_changed|live_new|live_incomplete|snapshot_fallback
    text: str                        # the text to use (live when it changed, otherwise the snapshot's)
    snapshot_text: str
    snapshot_at: str                 # when the index record was fetched (ISO)
    checked: str                     # Asia/Taipei minute of this check
    error: str = ""                  # why the live side failed, if it did
    detail: str = ""
    comparison: Comparison | None = None
    render_seconds: float = 0.0
    requests: int = 0                # HTTP requests it took (httpx: the page + redirects; Chromium: everything the page loaded)
    requests_nccu: int = 0
    method: str = "httpx"            # how the text we used was obtained: httpx | chromium
    escalated: str = ""              # why a static result was not enough (rag/live/escalate.py), if it was
    static_requests: int = 0         # httpx requests spent before escalating (so the cost of escalation is visible)
    tls_unverified: bool = False     # fetched over a connection whose certificate could not be verified (cashier)
    handled: Any = None              # whatever `handler` returned
    handler_error: str = ""


@dataclass
class ContactsResult:
    pages: dict[str, PageOutcome] = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)      # offices with no index record -> snapshot path
    order: list[str] = field(default_factory=list)          # order the pages finished in

    @property
    def texts(self) -> dict[str, str]:
        return {u: p.text for u, p in self.pages.items()}

    @property
    def parsed(self) -> dict[str, list]:
        """Contacts the handler already parsed, for pages where it succeeded and returned a list."""
        return {u: p.handled for u, p in self.pages.items() if isinstance(p.handled, list) and not p.handler_error}


def _default_handler(outcome: PageOutcome):
    from rag.skills.office_lookup_skill import parse_office_contacts
    return parse_office_contacts(outcome.text)


def plan_pages(offices: list[str]) -> tuple[dict[str, dict], list[str]]:
    """{url: {"offices": [...], "snapshot_text": str, "snapshot_at": str}}, plus offices the index does not cover."""
    from rag.skills.office_lookup_skill import index_records_for_office
    pages: dict[str, dict] = {}
    uncovered: list[str] = []
    for office in dict.fromkeys(offices):
        recs = [r for r in index_records_for_office(office) if r.get("url")]
        if not recs:
            uncovered.append(office)
        for rec in recs:
            p = pages.setdefault(rec["url"], {"offices": [], "snapshot_text": rec.get("text", ""),
                                              "snapshot_at": rec.get("fetched_at", "")})
            if office not in p["offices"]:
                p["offices"].append(office)
    return pages, uncovered


def _decide_static(url: str, info: dict, live: LiveResult) -> PageOutcome:
    res = R.resolve(info["snapshot_text"], live)
    n = 0 if live.error == "blocked_host" else max(1, live.attempts) + len(live.redirects)
    return PageOutcome(
        url=url, offices=info["offices"], state=_STATE[res.state], text=res.text, snapshot_text=info["snapshot_text"],
        snapshot_at=info["snapshot_at"], checked=taipei_minute(), error=live.error, detail=live.detail,
        comparison=res.comparison, render_seconds=live.elapsed, requests=n, requests_nccu=n, method="httpx",
        tls_unverified=live.tls_unverified)


def _decide_rendered(url: str, info: dict, rendered) -> PageOutcome:
    if rendered.ok:
        text, err = html_to_text(rendered.html, url)
    else:
        text, err = "", rendered.error
    live = LiveResult(url, ok=(err == ""), text=text, error=err, detail=rendered.detail, fetched_at=time.time())
    res = R.resolve(info["snapshot_text"], live)
    return PageOutcome(
        url=url, offices=info["offices"], state=_STATE[res.state], text=res.text, snapshot_text=info["snapshot_text"],
        snapshot_at=info["snapshot_at"], checked=taipei_minute(), error=err, detail=rendered.detail,
        comparison=res.comparison, render_seconds=rendered.elapsed,
        requests=rendered.requests, requests_nccu=rendered.requests_nccu, method="chromium")


def default_backends() -> tuple[Callable[[str], LiveResult], Callable[[str], "Future"]]:
    """(static fetch, Chromium render) for production: the process-wide httpx fetcher and browser-owner thread, which share
    one rate limiter, so the per-host gap holds across both kinds of request."""
    from rag.live.browser import get_owner
    from rag.live.hook import get_fetcher
    fetcher = get_fetcher()
    return (lambda url: fetcher.fetch(url, kind="contact", use_cache=False)), get_owner().render


def _run_handler(outcome: PageOutcome, handler) -> None:
    try:
        outcome.handled = handler(outcome)
    except Exception as e:                              # noqa: BLE001 -- one page's parse must not sink the others
        outcome.handler_error = f"{type(e).__name__}: {e}"[:200]
        log.warning("handler failed for %s: %s", outcome.url, outcome.handler_error)


def process_page(url: str, info: dict, fetch_static: Callable[[str], LiveResult], render: Callable[[str], "Future"],
                 handler: Callable[[PageOutcome], Any] | None = None) -> PageOutcome:
    """One staff page, start to finish: static fetch -> compare -> A/B -> parse -> C -> (maybe) Chromium. Used by
    fetch_contact_pages and by the prefetch (which runs it before contact_node asks)."""
    handler = handler or _default_handler
    try:
        live = fetch_static(url)
    except Exception as e:                              # noqa: BLE001 -- failure is data
        live = LiveResult(url, error="network", detail=f"{type(e).__name__}: {e}"[:200])
    similarity = static_similarity(info["snapshot_text"], live)
    reason = pre_parse_reason(live, similarity)         # A, B: decided without parsing
    outcome = _decide_static(url, info, live)
    if reason is None:
        _run_handler(outcome, handler)
        reason = post_parse_reason(outcome.handled) if live.ok and not outcome.handler_error else None   # C
    if reason is None:
        return outcome
    # the static result is not enough: let Chromium read the page
    static_requests = outcome.requests
    log.info("escalating %s to Chromium (%s)", url, reason)
    try:
        rendered = render(url).result()
    except Exception as e:                              # noqa: BLE001
        from rag.live.browser import RenderResult
        rendered = RenderResult(url, error="render_error", detail=f"{type(e).__name__}: {e}"[:200])
    final = _decide_rendered(url, info, rendered)
    final.escalated, final.static_requests = reason, static_requests
    _run_handler(final, handler)
    return final


def fetch_contact_pages(offices: list[str], fetch_static: Callable[[str], LiveResult],
                        render: Callable[[str], "Future"], handler: Callable[[PageOutcome], Any] | None = None,
                        workers: int | None = None, store=None) -> ContactsResult:
    """Blocks until every page is settled. Never raises for a page problem: a failed page falls back to the snapshot text.

    fetch_static(url) -> LiveResult (see rag.live.fetcher); render(url) -> Future[RenderResult] (see rag.live.browser).
    A page the prefetch (rag/live/prefetch.py) has already started or finished is taken from there instead of being fetched again."""
    from rag.live.prefetch import get_store
    store = store or get_store()
    handler = handler or _default_handler
    pages, uncovered = plan_pages(offices)
    result = ContactsResult(uncovered=uncovered)
    if not pages:
        return result

    grp = events.current_group()                        # the contact_node's progress group, if it opened one; workers inherit it (S5)

    def page_task(url: str) -> PageOutcome:
        info = pages[url]
        title = "、".join(info["offices"]) + " 人員頁"
        rid = grp.row("start", url=url, title=title, state="pending", kind="contact") if grp else None
        t0 = time.monotonic()
        outcome = store.contact(url, lambda: process_page(url, info, fetch_static, render, handler))
        # the prefetch may have worked out a different office list for this page than the one asked for now
        outcome = dataclasses.replace(outcome, offices=info["offices"])
        if grp:
            grp.row("done", rid=rid, url=url, title=title, state=outcome.state, checked=outcome.checked, tls_unverified=outcome.tls_unverified,
                    snap=(outcome.snapshot_at or config.SNAPSHOT_ASOF)[:10], seconds=time.monotonic() - t0, kind="contact")
        return outcome

    finished: list[str] = []
    lock = threading.Lock()

    def tracked(url: str) -> PageOutcome:
        try:
            return page_task(url)
        finally:
            with lock:
                finished.append(url)

    n_workers = workers or min(len(pages), 16)          # sleeping in the limiter is cheap; never queue a ready host behind a waiting one
    with ThreadPoolExecutor(max_workers=n_workers, thread_name_prefix="contact-page") as pool:
        futures = {url: events.submit_with_context(pool, tracked, url) for url in pages}     # workers need the run context to emit
        for url, fut in futures.items():
            result.pages[url] = fut.result()
    result.order = list(finished)
    for o in result.pages.values():
        log.info("live contact page %s -> %s via %s%s (%.1fs, %d requests) offices=%s", o.url, o.state, o.method,
                 f" [escalated: {o.escalated}]" if o.escalated else "", o.render_seconds, o.requests, o.offices)
    return result
