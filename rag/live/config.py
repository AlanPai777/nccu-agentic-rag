"""
rag/live/config.py
Phase J live-fetch settings (docs/phase_j_live_fetch_plan.md §5.4-5.5, D8-D14). Everything that is a
tunable *estimate* lives here and can be overridden by environment variable; nothing else in
rag/live/ hard-codes a number.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# D11: same string the original crawler (NCCU-Crawler) used; Playwright keeps Chromium's default.
USER_AGENT = "Mozilla/5.0 (compatible; NCCU-Edu-Crawler/1.0; +https://www.nccu.edu.tw) Academic research bot"

# Build date of the git-tracked snapshot corpus (aca pages 2026-08-19; the FTS index 2026-08-26). The jsonl
# rows carry no per-page fetch time, so this one date is what answers say the fallback data is "as of".
SNAPSHOT_ASOF = os.environ.get("LIVE_SNAPSHOT_ASOF", "2026-08-19")

ALLOWED_DOMAIN = "nccu.edu.tw"          # exact host or any subdomain; nothing else is ever fetched
# User decision 2026-10-14: cashier's server omits its intermediate certificate, so httpx cannot
# verify it. Explicit single-host list; every use is logged and flagged `tls_unverified`.
INSECURE_TLS_HOSTS = frozenset({"cashier.nccu.edu.tw"})
LEGACY_RENEGOTIATION_HOSTS = frozenset({"moltke.nccu.edu.tw"})  # old-style TLS renegotiation, verification stays on


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def live_mode() -> str:
    """LIVE_FETCH=off|on (default off). Anything unrecognised is treated as off."""
    return "on" if os.environ.get("LIVE_FETCH", "off").strip().lower() == "on" else "off"


# --- requests -------------------------------------------------------------------------------
REQUEST_TIMEOUT = _env_float("LIVE_REQUEST_TIMEOUT", 60.0)   # D8: one request, not the whole question
MAX_RETRIES = _env_int("LIVE_MAX_RETRIES", 2)
BACKOFF_BASE = _env_float("LIVE_BACKOFF_BASE", 1.0)          # 1s, 2s, ...
RETRY_AFTER_CAP = 120.0
MAX_REDIRECTS = 5
MAX_BODY_BYTES = 20_000_000

# --- browser rendering (P4; the browser-owner thread, rag/live/browser.py) -------------------------------------
BROWSER_IDLE_SECONDS = _env_float("LIVE_BROWSER_IDLE", 600.0)     # close Chromium after this long unused (estimate)
RENDER_SETTLE_MS = _env_int("LIVE_RENDER_SETTLE_MS", 2000)        # wait after `load` for late JS (same as fetch_office_contacts.py)
RENDER_NAV_TIMEOUT_MS = int(REQUEST_TIMEOUT * 1000)               # D8: one page, 60 s
# Starting guess for how long one render takes, used by the scheduler until it has seen real ones (then it uses their
# running mean). 3 s = P0's measurement on nine staff pages; the 2026-08-25 index crawl averaged 6.4 s per URL.
RENDER_ESTIMATE_SECONDS = _env_float("LIVE_RENDER_ESTIMATE", 3.0)

# Staff pages are fetched with httpx first; the page is sent to Chromium only when the static result looks insufficient
# (rag/live/escalate.py). A static page whose normalized text is less similar to the snapshot than this is escalated.
# 0.5 is a guess backed by nine samples: the 2026-10-14 staff pages scored 0.905-0.999 against the snapshot, the one that
# needs JavaScript (oic) scored 0.016. Cheap to be wrong in the escalating direction (one more render), costly the other way.
STATIC_SIMILARITY_MIN = _env_float("LIVE_STATIC_SIMILARITY_MIN", 0.5)

# --- rate limiting (§5.5) -------------------------------------------------------------------
GLOBAL_CONCURRENCY = _env_int("LIVE_GLOBAL_CONCURRENCY", 4)  # prototype start; raise if no throttling seen


@dataclass(frozen=True)
class HostPolicy:
    min_interval: float   # seconds between request *starts* to this host
    concurrency: int


DEFAULT_POLICY = HostPolicy(min_interval=_env_float("LIVE_HOST_INTERVAL", 1.0), concurrency=2)
HOST_POLICY: dict[str, HostPolicy] = {
    "osa.nccu.edu.tw": HostPolicy(10.0, 1),      # robots.txt: Crawl-delay 10 (P0 finding, decision A: obey)
    "moltke.nccu.edu.tw": HostPolicy(0.5, 2),    # original crawler used 0.5s; each form has its own cookie jar, so 2 in flight is safe
    "cpbae.nccu.edu.tw": HostPolicy(5.0, 1),     # original crawler: 92% 429 (tentative)
}


def host_policy(host: str) -> HostPolicy:
    return HOST_POLICY.get(host.lower(), DEFAULT_POLICY)


# A live page whose normalized text is shorter than this fraction of the snapshot's is treated as an
# incomplete static render (JS-built page), not as an edit. Estimate; P1 saw 37 vs 4956 chars (oic).
INCOMPLETE_RATIO = _env_float("LIVE_INCOMPLETE_RATIO", 0.5)

# --- circuit breaker (§5.4) -----------------------------------------------------------------
BREAKER_THRESHOLD = _env_int("LIVE_BREAKER_THRESHOLD", 5)
BREAKER_COOLDOWN = _env_float("LIVE_BREAKER_COOLDOWN", 300.0)

# --- cache (§5.3; estimates, tune after measuring) ------------------------------------------
CACHE_DIR = ROOT / "rag" / "live" / "_cache"
CACHE_DB = CACHE_DIR / "live.sqlite"
TTL_SECONDS = {
    "page": _env_int("LIVE_TTL_PAGE", 600),
    "listing": _env_int("LIVE_TTL_LISTING", 300),
    "contact": _env_int("LIVE_TTL_CONTACT", 3600),
    "form": _env_int("LIVE_TTL_FORM", 3600),
    "pdf": _env_int("LIVE_TTL_PDF", 86400),
}

# --- slow-query warnings (§5.4, D9): warn only, never abort ---------------------------------
SLOW_WARN_SECONDS = (30, 60, 120, 300)
