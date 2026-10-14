"""
rag/live/resolve.py
Live-vs-snapshot decision (§5.2): same -> snapshot text; different -> live text; live failed -> snapshot.
Pure given a LiveResult, so it is testable without a network.
"""

from __future__ import annotations

from dataclasses import dataclass

from rag.live import config
from rag.live.compare import Comparison, compare, normalize
from rag.live.fetcher import LiveResult

LIVE_SAME = "live_same"            # confirmed live, matches the snapshot
LIVE_CHANGED = "live_changed"      # confirmed live, content differs -> live text is used
LIVE_ONLY = "live_only"            # no snapshot exists for this URL
LIVE_INCOMPLETE = "live_incomplete"  # live fetch succeeded but looks like an unrendered JS page -> snapshot kept, needs Chromium
SNAPSHOT_FALLBACK = "snapshot_fallback"   # live fetch failed -> snapshot text, and the answer must say so


@dataclass
class Resolution:
    state: str
    text: str
    comparison: Comparison | None
    live: LiveResult
    tls_unverified: bool = False


def resolve(snapshot_text: str | None, live: LiveResult) -> Resolution:
    if not live.ok:
        return Resolution(SNAPSHOT_FALLBACK, snapshot_text or "", None, live, live.tls_unverified)
    if not snapshot_text:
        return Resolution(LIVE_ONLY, live.text, None, live, live.tls_unverified)
    if len(normalize(live.text)) < config.INCOMPLETE_RATIO * len(normalize(snapshot_text)):
        return Resolution(LIVE_INCOMPLETE, snapshot_text, compare(snapshot_text, live.text), live, live.tls_unverified)
    cmp = compare(snapshot_text, live.text)
    return Resolution(LIVE_SAME if cmp.same else LIVE_CHANGED, snapshot_text if cmp.same else live.text,
                      cmp, live, live.tls_unverified)
