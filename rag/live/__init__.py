"""
rag/live/
Phase J live-fetch package (docs/phase_j_live_fetch_plan.md). Currently only
clock.py (P0); fetcher/compare/cache/ratelimit/... arrive in later stages.
"""


import logging as _logging
import os as _os

# LIVE_LOG=info (or debug) prints the rag.live logger to stderr -- fetch timings, diffs, failures. Off by default
# (the project configures no root logger, so INFO lines from rag.live would otherwise vanish).
_lvl = _os.environ.get("LIVE_LOG", "").strip().upper()
if _lvl in ("DEBUG", "INFO", "WARNING"):
    _h = _logging.StreamHandler()
    _h.setFormatter(_logging.Formatter("[live] %(message)s"))
    for _name in ("rag.live", "rag.form_gate"):
        _log = _logging.getLogger(_name)
        _log.setLevel(getattr(_logging, _lvl))
        _log.addHandler(_h)
