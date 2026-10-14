"""
rag/live/hook.py
The single call site get_page_tool uses. P1: LIVE_FETCH=off (default) returns the snapshot dict
untouched, so agent behaviour is unchanged; `on` is wired in P2, until then it only warns.
"""

from __future__ import annotations

import logging

from rag.live.config import live_mode

log = logging.getLogger("rag.live")


def apply_page(page: dict) -> dict:
    if live_mode() == "off":
        return page
    log.warning("LIVE_FETCH=on requested but the page hook is not wired until P2; using snapshot")
    return page
