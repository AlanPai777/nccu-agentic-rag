"""
rag/live/sources.py
The "sources" the front end shows: every page, form or contact record whose CONTENT reached the
model while it wrote the answer, grouped by site, each with how it was checked (live, or database) and when.

Built from the ledger markers in state["messages"] (rag/live/ledger.py), the same source the 【資料狀態】 section uses, so the two cannot
disagree. What is NOT a source: a page the search or grep tools only returned as a title and a URL (its content never reached the model), and
the links extract_links listed. A question that turned live off still records what it read, as "snapshot" markers (rag/live/hook.py,
rag/agentic/nodes/contact.py), so it lists its pages too, labelled as database data.
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from rag.live import config
from rag.live.ledger import FIXED_DATA, Source, label, parse_markers, time_text
from rag.live.site_names import site_name

FIXED_GROUP = "fixed"
FIXED_NAME = "內建固定資料"


def _title(src: Source) -> str:
    if src.status == FIXED_DATA:
        return src.url.rsplit("/", 1)[-1] or "內建固定聯絡資料"
    if src.title:
        return src.title
    path = unquote(urlparse(src.url).path).rstrip("/").rsplit("/", 1)[-1]
    return path or urlparse(src.url).netloc


def _item(src: Source) -> dict:
    fixed = src.status == FIXED_DATA
    return {
        "title": _title(src),
        "kind": src.kind,
        "url": "" if fixed else src.url,                 # fixed data is not a web page: nothing to open
        "state": src.status,
        "label": label(src, short=True),
        "checked": src.checked or None,
        "time": time_text(src),
        "cached": src.cached,
        "age_min": src.age_min,
        "tls_unverified": src.tls_unverified,
    }


def build_sources(messages: list, live: bool) -> dict:
    """The payload of the {"type":"sources"} SSE event. Groups appear in the order their first page was read. Items keep reading order."""
    groups: dict[str, dict] = {}
    for src in parse_markers(messages):
        host = FIXED_GROUP if src.status == FIXED_DATA else urlparse(src.url).netloc.lower()
        g = groups.setdefault(host, {"host": host, "name": FIXED_NAME if host == FIXED_GROUP else site_name(host), "items": []})
        g["items"].append(_item(src))
    return {"type": "sources", "live": bool(live), "snapshot_date": config.SNAPSHOT_ASOF, "groups": list(groups.values())}
