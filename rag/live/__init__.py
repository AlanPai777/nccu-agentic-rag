"""
rag/live/
Checks pages against nccu.edu.tw while a question is answered. The settings are in config.py, fetching in fetcher.py,
and the comparison with the snapshot in compare.py and resolve.py.
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
