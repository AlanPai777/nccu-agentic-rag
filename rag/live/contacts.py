"""
rag/live/contacts.py
Live staff pages for the offices contact_node found (docs/phase_j_live_fetch_plan.md, P4 step 4).

For each office: the office_contacts_index.jsonl record(s) say WHICH page lists its staff (the same lookup the snapshot
path does). Those pages are rendered in Chromium (RenderScheduler -> browser-owner thread), turned into text with the
snapshot's own extractor, compared with the text stored in the index (rag/live/resolve.py: same -> snapshot, different ->
live, live failed or incomplete -> snapshot, flagged), and each page is handed to `handler` AS SOON AS it is ready --
the pipeline: parsing (which may call an LLM for some page layouts) overlaps with the browser loading the next page.

Offices with no index record are returned in `uncovered`: they stay on the snapshot path and the answer says so.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from rag.live import ledger, resolve as R
from rag.live.clock import taipei_minute
from rag.live.compare import Comparison
from rag.live.extract import html_to_text
from rag.live.fetcher import LiveResult
from rag.live.schedule import RenderScheduler

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
    handled: Any = None              # whatever `handler` returned
    handler_error: str = ""


@dataclass
class ContactsResult:
    pages: dict[str, PageOutcome] = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)      # offices with no index record -> snapshot path
    order: list[str] = field(default_factory=list)          # order the pages were rendered in

    @property
    def texts(self) -> dict[str, str]:
        return {u: p.text for u, p in self.pages.items()}

    @property
    def parsed(self) -> dict[str, list]:
        """Contacts the handler already parsed, for pages where it succeeded and returned a list."""
        return {u: p.handled for u, p in self.pages.items() if isinstance(p.handled, list) and not p.handler_error}


def default_scheduler() -> RenderScheduler:
    """The process-wide browser-owner thread, paced by the same limiter as the httpx fetcher."""
    from rag.live.browser import get_owner
    from rag.live.hook import get_fetcher
    return RenderScheduler(get_owner().render, get_fetcher().limiter)


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


def _decide(url: str, info: dict, rendered) -> PageOutcome:
    if rendered.ok:
        text, err = html_to_text(rendered.html, url)
    else:
        text, err = "", rendered.error
    live = LiveResult(url, ok=(err == ""), text=text, error=err, detail=rendered.detail, fetched_at=time.time())
    res = R.resolve(info["snapshot_text"], live)
    return PageOutcome(
        url=url, offices=info["offices"], state=_STATE[res.state], text=res.text, snapshot_text=info["snapshot_text"],
        snapshot_at=info["snapshot_at"], checked=taipei_minute(), error=err, detail=rendered.detail,
        comparison=res.comparison, render_seconds=rendered.elapsed)


def fetch_contact_pages(offices: list[str], scheduler: RenderScheduler,
                        handler: Callable[[PageOutcome], Any] | None = None, workers: int = 4) -> ContactsResult:
    """Blocks until every page has been rendered, decided and handled. Never raises for a page problem."""
    handler = handler or _default_handler
    pages, uncovered = plan_pages(offices)
    result = ContactsResult(uncovered=uncovered)
    if not pages:
        return result
    def process(url: str, rendered) -> PageOutcome:
        outcome = _decide(url, pages[url], rendered)
        try:
            outcome.handled = handler(outcome)
        except Exception as e:                          # noqa: BLE001 -- one page's parse must not sink the others
            outcome.handler_error = f"{type(e).__name__}: {e}"[:200]
            log.warning("handler failed for %s: %s", url, outcome.handler_error)
        return outcome

    futures = scheduler.run(list(pages))
    url_of = {f: u for u, f in futures.items()}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="contact-page") as pool:
        work = []
        # The pipeline: the moment a page has been rendered it goes to the pool, while the scheduler thread is already
        # sending the browser the next page.
        for fut in as_completed(futures.values()):
            work.append(pool.submit(process, url_of[fut], fut.result()))
        for w in work:
            o = w.result()
            result.pages[o.url] = o
    result.order = list(scheduler.order)
    for o in result.pages.values():
        log.info("live contact page %s -> %s (%.1fs render) offices=%s", o.url, o.state, o.render_seconds, o.offices)
    return result
