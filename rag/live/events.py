"""
rag/live/events.py
Live progress events for the front end. Every tool or node that reads something says so as it
goes, with LangGraph's custom stream, and server.py forwards the events as SSE:

    {"type":"step","kind":"group","id":"g1","verb":"page","title":"休學…","phase":"start"|"done","seconds":2.4}
    {"type":"step","kind":"row","group_id":"g1","id":"r1","phase":"start"|"done","host":…,"site_name":…,"title":…,"url":…,"state":…,
     "label":…,"time":…,"checked":…,"cached":…,"age_min":…,"seconds":…,"tls_unverified":…}

A group is one tool action (search, grep, page, form, contacts, links). Its rows are the pages it read. A row with the same id updates the
earlier one (start -> done). Nothing here may ever hurt the question: every emit is wrapped, and without a listener (graph.invoke, the CLI)
it does nothing.

Threads: LangGraph's writer only works inside the run context. A thread-pool worker
or a plain thread gets "Called get_config outside of a runnable context" while a stream is being consumed (and says nothing under invoke), so
work that may emit from another thread must be started with submit_with_context / start_thread_with_context, which run it in a copy of the
caller's context. The current group travels the same way (a ContextVar), so a worker's rows land in the right group.
"""

from __future__ import annotations

import contextvars
import itertools
import logging
import threading
import time
from contextlib import contextmanager
from urllib.parse import unquote, urlparse

from rag.live import config
from rag.live.ledger import Source, label, source_from_marker, time_text
from rag.live.site_names import site_name

log = logging.getLogger("rag.live")

_group: contextvars.ContextVar["Group | None"] = contextvars.ContextVar("live_event_group", default=None)
_counter = itertools.count(1)

PENDING_LABEL = {"pending": "讀取中…", "waiting": "等待中（同網站需間隔一段時間）"}


def _next(prefix: str) -> str:
    return f"{prefix}{next(_counter)}"


def emit(event: dict) -> None:
    """Send one custom event to whoever streams this run. Never raises. A no-op outside a graph run or when nobody listens."""
    try:
        from langgraph.config import get_stream_writer
        get_stream_writer()(event)
    except Exception as e:                                      # noqa: BLE001 -- progress is an addition, never a dependency
        log.debug("event not sent: %s: %s", type(e).__name__, e)


def submit_with_context(executor, fn, *args, **kwargs):
    """executor.submit(...) whose work runs in a COPY of the caller's context (a fresh copy per task: one Context cannot be entered by two
    threads at once), so it can emit and sees the current group."""
    return executor.submit(contextvars.copy_context().run, fn, *args, **kwargs)


def start_thread_with_context(target, *args, name: str | None = None) -> threading.Thread:
    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(target, *args), name=name, daemon=True)
    t.start()
    return t


def title_list(names: list[str], limit: int = 3) -> str:
    """'註冊組、教務長室、出納組 …': the first few names, then an ellipsis when there are more (the UI truncates long titles anyway)."""
    names = [n for n in names if n]
    return "、".join(names[:limit]) + (" …" if len(names) > limit else "")


def url_title(url: str) -> str:
    return unquote(urlparse(url).path).rstrip("/").rsplit("/", 1)[-1] or urlparse(url).netloc


class Group:
    def __init__(self, gid: str, verb: str, title: str):
        self.id, self.verb, self.title = gid, verb, title
        self._done = 0
        self._first_row_title = ""
        self.refine = False         # replace the title by the first finished row's title (+ " …" if there were more) when the group ends

    def row(self, phase: str, *, url: str = "", title: str = "", state: str = "snapshot", rid: str | None = None, marker: str | None = None,
            seconds: float | None = None, kind: str = "page", snap: str = "", checked: str = "", cached: bool = False,
            age_min: int | None = None, tls_unverified: bool = False) -> str:
        """Emit one row of this group and return its id (pass it back as rid for the done event). With `marker` (a live_marker line) the
        state, check time, cache info and snapshot date come from it, so a row says exactly what the ledger and the sources panel say."""
        rid = rid or _next("r")
        src = source_from_marker(marker) if marker else None
        if src is not None:
            state, checked, cached, age_min, tls_unverified, snap, kind = (src.status, src.checked, src.cached, src.age_min,
                                                                           src.tls_unverified, src.snap or snap, src.kind or kind)
            title = title or src.title
        snap = snap or config.SNAPSHOT_ASOF
        if state in PENDING_LABEL:
            lab, when = PENDING_LABEL[state], ""
        else:
            s = Source(url, state, checked, snap, tls_unverified, kind, cached, age_min, title)
            lab, when = label(s, short=True), time_text(s)
        host = urlparse(url).netloc.lower()
        if phase == "done":
            self._done += 1
            if not self._first_row_title and (title or (src and src.title)):
                self._first_row_title = title or src.title
        emit({"type": "step", "kind": "row", "group_id": self.id, "id": rid, "phase": phase, "host": host, "site_name": site_name(host) if host else "",
              "title": title or url_title(url), "url": url, "state": state, "label": lab, "time": when, "checked": checked or None,
              "cached": cached, "age_min": age_min, "seconds": None if seconds is None else round(seconds, 1), "tls_unverified": tls_unverified,
              "row_kind": kind})
        return rid


@contextmanager
def group(verb: str, title: str, refine: bool = False):
    """One tool action. Rows emitted inside (also from workers started with submit_with_context) belong to it. `title` may be refined by
    setting group.title before the block ends: the done event carries the final one."""
    g = Group(_next("g"), verb, title)
    g.refine = refine
    t0 = time.monotonic()
    emit({"type": "step", "kind": "group", "id": g.id, "verb": verb, "title": title, "phase": "start", "seconds": None})
    token = _group.set(g)
    try:
        yield g
    finally:
        _group.reset(token)
        if g.refine and g._first_row_title:
            g.title = g._first_row_title + (" …" if g._done > 1 else "")
        emit({"type": "step", "kind": "group", "id": g.id, "verb": verb, "title": g.title, "phase": "done",
              "seconds": round(time.monotonic() - t0, 1)})


def current_group() -> Group | None:
    """The group the running code is inside (set by `group`), or None. Lets a helper such as the form fetch add a row without knowing
    whether its caller opened a group."""
    return _group.get()
