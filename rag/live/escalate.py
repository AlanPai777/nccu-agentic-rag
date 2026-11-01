"""
rag/live/escalate.py
When is a static (httpx) result for a staff page not enough, so that Chromium must read the page?

  A. the fetch itself says so: the page came back with no content, or is a Cloudflare challenge, or the server answered 403.
     (Timeouts, 429, 5xx, an open circuit breaker, a redirect off the allowlist do NOT escalate: when the server is unhappy a
     second, heavier visit only makes it worse -- the caller falls back to the snapshot and says so.)
  B. the static text is very different from the snapshot's (similarity below config.STATIC_SIMILARITY_MIN).
  C. the static text yields no contact at all. This one does NOT look at the snapshot: the snapshot can itself be poor
     (oic's lost every name to an extractor bug, so "the snapshot had people" would have kept oic off Chromium forever).

A and B are decided before parsing, which may call an LLM. C needs the parse. Returns a short reason string, or None.
A wrong "no" costs missing data, a wrong "yes" costs one more page render, so the thresholds lean towards escalating.

Known blind spot (recorded in the plan, not handled): static and snapshot are equally poor while Chromium would show more, or
a page is missing only part of its list. Only fetching the page both ways can reveal that.

fetch_with_escalation() runs the whole sequence for one page: the static fetch, the caller's checks, and at most one browser
render. It knows nothing about staff pages or contacts. The caller supplies the checks, so a staff page can add the parse and
condition C while any other page uses only the checks that look at the fetch itself.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from rag.live import config
from rag.live.compare import Comparison, compare, normalize
from rag.live.extract import html_to_text
from rag.live.fetcher import LiveResult

log = logging.getLogger("rag.live")

ESCALATING_ERRORS = frozenset({"empty", "cloudflare"})


@dataclass
class Escalated:
    static: LiveResult           # the httpx result, always present
    rendered: Any = None         # the browser's RenderResult when the page was escalated, otherwise None
    reason: str = ""             # why the page was escalated, empty when it was not


def fetch_with_escalation(url: str, fetch_static: Callable[[str], LiveResult], render: Callable[[str], "Future"],
                          pre_reason: Callable[[LiveResult], str | None],
                          post_reason: Callable[[LiveResult], str | None] | None = None) -> Escalated:
    """Static fetch, then a browser render only when a check asks for one. Never raises for a fetch or render problem: a failure
    becomes a LiveResult or RenderResult carrying the error, which the caller decides how to treat.

    fetch_static(url) -> LiveResult (see rag.live.fetcher). render(url) -> Future[RenderResult] (see rag.live.browser).
    pre_reason(live) decides from the fetch alone. post_reason(live) runs only when pre_reason found nothing, for a check that
    needs work on the static text first (a staff page parses it, then asks whether any contact came out)."""
    try:
        live = fetch_static(url)
    except Exception as e:                              # noqa: BLE001 -- failure is data
        live = LiveResult(url, error="network", detail=f"{type(e).__name__}: {e}"[:200])
    reason = pre_reason(live)
    if reason is None and post_reason is not None:
        reason = post_reason(live)
    if reason is None:
        return Escalated(static=live)
    log.info("escalating %s to Chromium (%s)", url, reason)
    try:
        rendered = render(url).result()
    except Exception as e:                              # noqa: BLE001
        from rag.live.browser import RenderResult
        rendered = RenderResult(url, error="render_error", detail=f"{type(e).__name__}: {e}"[:200])
    return Escalated(static=live, rendered=rendered, reason=reason)


def static_similarity(snapshot_text: str, live: LiveResult) -> float | None:
    """None when there is nothing to compare (no snapshot, or the fetch failed)."""
    if not live.ok or not snapshot_text:
        return None
    c: Comparison = compare(snapshot_text, live.text)
    return c.similarity


def fetch_reason(live: LiveResult) -> str | None:
    """Condition A, which only looks at the fetch itself and so applies to any kind of page."""
    if live.ok:
        return None
    if live.error in ESCALATING_ERRORS:
        return f"A:{live.error}"
    if live.error == "http_4xx" and live.status == 403:
        return "A:http_403"
    return None


def pre_parse_reason(live: LiveResult, similarity: float | None, minimum: float | None = None) -> str | None:
    """Conditions A and B for a staff page. B compares with the snapshot by similarity, which is meaningful there because the
    staff snapshot was rendered in a browser, so a static page that differs a lot is missing what the browser showed."""
    reason = fetch_reason(live)
    if reason is not None or not live.ok:
        return reason
    minimum = config.STATIC_SIMILARITY_MIN if minimum is None else minimum
    if similarity is not None and similarity < minimum:
        return f"B:similarity={similarity:.3f}<{minimum:g}"
    return None


def shorter_reason(live: LiveResult, snapshot_text: str | None, ratio: float | None = None) -> str | None:
    """Condition B for any other page: the static text is much shorter than the snapshot's. Similarity is not used here because the
    snapshot of such a page was fetched statically too, so it cannot contain what only a browser shows. A drop in length is what a
    page that has turned into one needing JavaScript looks like, and it does not fire on a page that grew or was rewritten."""
    if not live.ok or not snapshot_text:
        return None
    ratio = config.ESCALATE_BELOW_RATIO if ratio is None else ratio
    live_len, snap_len = len(normalize(live.text)), len(normalize(snapshot_text))
    if snap_len and live_len < ratio * snap_len:
        return f"B:shorter={live_len}/{snap_len}<{ratio:g}"
    return None


def page_pre_reason(live: LiveResult, snapshot_text: str | None) -> str | None:
    """A, then B by length, for a page that is not a staff page."""
    return fetch_reason(live) or shorter_reason(live, snapshot_text)


def live_from_render(url: str, rendered: Any) -> LiveResult:
    """The browser's RenderResult as the LiveResult the rest of the code compares with the snapshot."""
    if rendered.ok:
        text, err = html_to_text(rendered.html, url)
    else:
        text, err = "", rendered.error
    return LiveResult(url, ok=(err == ""), text=text, error=err, detail=rendered.detail, fetched_at=time.time())


def post_parse_reason(contacts) -> str | None:
    """Condition C. Only meaningful when the handler returned a list of contacts."""
    if isinstance(contacts, list) and len(contacts) == 0:
        return "C:no_contacts"
    return None
