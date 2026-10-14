"""
rag/live/clock.py
Reference date for time-intent parsing (Phase J P0, docs/phase_j_live_fetch_plan.md
§5.12). "今天" / "10/14" / "本週" can only be resolved against a known "today";
AgentState.today is filled from here once per turn by agentic_rag.initial_state().

No node reads state["today"] yet (P0 adds the field only, behaviour unchanged).
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def today_taipei() -> str:
    """ISO date (YYYY-MM-DD) in Asia/Taipei.

    LIVE_TODAY=YYYY-MM-DD overrides it (tests and recorded fixtures need a
    fixed "today"). A malformed override raises instead of silently falling
    back to the real clock -- a wrong "today" would quietly shift every time
    window downstream.
    """
    override = os.environ.get("LIVE_TODAY", "").strip()
    if override:
        datetime.strptime(override, "%Y-%m-%d")
        return override
    return datetime.now(TAIPEI).strftime("%Y-%m-%d")


def taipei_minute(ts: float | None = None) -> str:
    """'YYYY-MM-DDTHH:MM' in Asia/Taipei for a unix timestamp (default: now). Used in source markers."""
    dt = datetime.fromtimestamp(ts, TAIPEI) if ts is not None else datetime.now(TAIPEI)
    return dt.strftime("%Y-%m-%dT%H:%M")
