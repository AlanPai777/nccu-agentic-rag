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
"""

from __future__ import annotations

from rag.live import config
from rag.live.compare import Comparison, compare
from rag.live.fetcher import LiveResult

ESCALATING_ERRORS = frozenset({"empty", "cloudflare"})


def static_similarity(snapshot_text: str, live: LiveResult) -> float | None:
    """None when there is nothing to compare (no snapshot, or the fetch failed)."""
    if not live.ok or not snapshot_text:
        return None
    c: Comparison = compare(snapshot_text, live.text)
    return c.similarity


def pre_parse_reason(live: LiveResult, similarity: float | None, minimum: float | None = None) -> str | None:
    """Conditions A and B."""
    if not live.ok:
        if live.error in ESCALATING_ERRORS:
            return f"A:{live.error}"
        if live.error == "http_4xx" and live.status == 403:
            return "A:http_403"
        return None
    minimum = config.STATIC_SIMILARITY_MIN if minimum is None else minimum
    if similarity is not None and similarity < minimum:
        return f"B:similarity={similarity:.3f}<{minimum:g}"
    return None


def post_parse_reason(contacts) -> str | None:
    """Condition C. Only meaningful when the handler returned a list of contacts."""
    if isinstance(contacts, list) and len(contacts) == 0:
        return "C:no_contacts"
    return None
