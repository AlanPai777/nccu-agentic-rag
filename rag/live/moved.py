"""
rag/live/moved.py
Pages that moved to a new URL (F19: the general-affairs units' staff pages moved from their own sub-domains to nccuga.nccu.edu.tw).

moved_pages.json lists the exact old URLs. Every place that READS a page live asks here first:

    fetch_target(url)        the URL to request (the new one when the page moved, otherwise `url` itself)
    shown(url, live_ok)      (url to show as the source, moved_from, moved_to):
                             live read succeeded  -> the NEW url is the source (moved_from = the old url)
                             snapshot only/failed -> the OLD url stays the source, with moved_to = the new url so the answer can say
                                                     "the official URL moved to ..."  (the content is the old page's, so naming the new
                                                     URL as the source would claim more than was read)

The snapshot is untouched: output/ and the contact index keep their old records and dates. Only the live layer is redirected.
Exact URLs only (percent-encoding, a fragment and a trailing slash are ignored), never a whole host: the old sub-domains still serve
other pages that did not move.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urldefrag

_PATH = Path(__file__).with_name("moved_pages.json")


@dataclass(frozen=True)
class Moved:
    old: str
    new: str
    since: str = ""
    note: str = ""
    unit: str = ""


_lock = threading.Lock()
_table: dict[str, Moved] | None = None


def _key(url: str) -> str:
    return unquote(urldefrag(url or "")[0]).rstrip("/")


def load(path: Path | None = None) -> dict[str, Moved]:
    """{normalised old url: Moved}. A missing or unreadable file means nothing moved (the live layer behaves as before)."""
    global _table
    with _lock:
        if path is None and _table is not None:
            return _table
        table: dict[str, Moved] = {}
        try:
            data = json.loads((path or _PATH).read_text(encoding="utf-8"))
            for p in data.get("pages", []):
                if p.get("old") and p.get("new"):
                    table[_key(p["old"])] = Moved(p["old"], p["new"], p.get("since", ""), p.get("note", ""), p.get("unit", ""))
        except (OSError, ValueError):
            table = {}
        if path is None:
            _table = table
        return table


def reset() -> None:
    """For tests: forget the loaded table."""
    global _table
    with _lock:
        _table = None


def lookup(url: str) -> Moved | None:
    return load().get(_key(url))


def fetch_target(url: str) -> str:
    m = lookup(url)
    return m.new if m else url


def new_for(url: str) -> str:
    """The new URL of a moved page, or '' (for a snapshot-only marker: it names where the page lives now)."""
    m = lookup(url)
    return m.new if m else ""


def shown(url: str, live_ok: bool) -> tuple[str, str, str]:
    """(source url to show, moved_from, moved_to) for a read of `url`; ('url', '', '') when the page did not move."""
    m = lookup(url)
    if m is None:
        return url, "", ""
    return (m.new, m.old, "") if live_ok else (url, "", m.new)
