"""
rag/live/config.py
Settings for checking pages against nccu.edu.tw while a question is answered. Every tunable number lives here
and can be overridden by an environment variable. Nothing else in rag/live/ hard-codes a number.
Most values are estimates, not measurements. The comment on each one says what it rests on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# Same string the earlier crawler used, so the live check adds no new identity to the university's access logs.
# The URL inside it points at the university home page, not at a project page.
# A site administrator can tell this is an academic research bot, but cannot reach us from it.
USER_AGENT = "Mozilla/5.0 (compatible; NCCU-Edu-Crawler/1.0; +https://www.nccu.edu.tw) Academic research bot"

# Build date of the git-tracked snapshot corpus. The aca pages date from 2026-08-19 and the FTS index from 2026-08-26. The jsonl
# rows carry no per-page fetch time, so this one date is what answers say the fallback data is "as of".
SNAPSHOT_ASOF = os.environ.get("LIVE_SNAPSHOT_ASOF", "2026-08-19")

ALLOWED_DOMAIN = "nccu.edu.tw"          # exact host or any subdomain, nothing else is ever fetched
# cashier's server does not send its intermediate certificate, so httpx cannot verify the certificate chain.
# It is the only host where verification is turned off. It is listed explicitly, every use is logged,
# and the page is flagged `tls_unverified` so the answer can say so.
# Other hosts with the same problem are described under "Known limitations" in docs/architecture.md.
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


def prefetch_enabled() -> bool:
    """LIVE_PREFETCH=on (default off): when a page with form ids is read, start the forms and staff pages it will lead to in the
    background, using the SNAPSHOT to work out what they are (rag/live/prefetch.py). Only meaningful together with LIVE_FETCH=on."""
    return os.environ.get("LIVE_PREFETCH", "off").strip().lower() == "on"


def live_mode() -> str:
    """LIVE_FETCH=off|on (default off). Anything unrecognised is treated as off."""
    return "on" if os.environ.get("LIVE_FETCH", "off").strip().lower() == "on" else "off"


def live_enabled(request_live: bool | None = None) -> bool:
    """Should this question confirm things live? `request_live` is the per-question choice (AgentState["live"]: the front end's
    "查現場" switch via /ask?live=, or the CLI's --live). None means the caller did not say.

      LIVE_FETCH=off (or anything unrecognised)  -> False always: the operator's kill switch beats any request
      LIVE_FETCH unset or empty                  -> the request decides, and no request means False (the CLI default, as before)
      LIVE_FETCH=on                              -> the request decides, and no request means True (as before)

    So with no request and no variable the behaviour is the same as before the per-question switch existed."""
    raw = os.environ.get("LIVE_FETCH", "").strip().lower()
    if raw not in ("", "on"):
        return False
    if request_live is not None:
        return bool(request_live)
    return raw == "on"


# --- requests -------------------------------------------------------------------------------
# One request, not the whole question. A request that times out counts as a failure of that one page.
# The answer then uses the snapshot for that page, marked as a fallback, and the other pages carry on.
# Without a timeout, one stuck connection could keep a question from ever finishing.
# httpx waits 5 s by default and Playwright navigation 30 s, so 60 s is more patient than both. It is a choice, not a measurement.
REQUEST_TIMEOUT = _env_float("LIVE_REQUEST_TIMEOUT", 60.0)
# A failed request is retried this many times, waiting longer each time, and a Retry-After header from the server is honoured.
MAX_RETRIES = _env_int("LIVE_MAX_RETRIES", 2)
BACKOFF_BASE = _env_float("LIVE_BACKOFF_BASE", 1.0)          # 1s, 2s, ...
RETRY_AFTER_CAP = 120.0                                      # the longest Retry-After wait we will honour, in seconds
MAX_REDIRECTS = 5
MAX_BODY_BYTES = 20_000_000

# --- browser rendering (the browser-owner thread, rag/live/browser.py) -------------------------------------
BROWSER_IDLE_SECONDS = _env_float("LIVE_BROWSER_IDLE", 600.0)     # close Chromium after this long unused (an estimate)
RENDER_SETTLE_MS = _env_int("LIVE_RENDER_SETTLE_MS", 2000)        # wait after `load` for late JS, the same wait as the script that built the staff-page index
RENDER_NAV_TIMEOUT_MS = int(REQUEST_TIMEOUT * 1000)               # one page, the same limit as one request
# Starting guess for how long one render takes. The scheduler uses it until it has seen real renders, then it uses their running mean.
# 3 s comes from measuring nine staff pages. The crawl that built the staff-page index averaged 6.4 s per URL.
RENDER_ESTIMATE_SECONDS = _env_float("LIVE_RENDER_ESTIMATE", 3.0)

# Staff pages are fetched with httpx first. The page is sent to Chromium only when the static result looks insufficient
# (rag/live/escalate.py). A static page whose normalized text is less similar to the snapshot than this is escalated.
# 0.5 is a guess backed by nine samples. Eight staff pages scored 0.905-0.999 against the snapshot, and the one page that needs
# JavaScript (oic) scored 0.016. A wrong guess toward escalating costs one more render. A wrong guess the other way accepts a
# half-empty page, so the threshold leans toward escalating.
STATIC_SIMILARITY_MIN = _env_float("LIVE_STATIC_SIMILARITY_MIN", 0.5)

# --- rate limiting, shared by the whole process -----------------------------------------------
# At most this many requests are in flight across all hosts. This is a starting value. Nothing shows that the university's
# servers tolerate more requests at once, so raise it only after seeing no throttling.
GLOBAL_CONCURRENCY = _env_int("LIVE_GLOBAL_CONCURRENCY", 4)


@dataclass(frozen=True)
class HostPolicy:
    min_interval: float   # seconds between request *starts* to this host
    concurrency: int


DEFAULT_POLICY = HostPolicy(min_interval=_env_float("LIVE_HOST_INTERVAL", 1.0), concurrency=2)
HOST_POLICY: dict[str, HostPolicy] = {
    "osa.nccu.edu.tw": HostPolicy(10.0, 1),      # its robots.txt asks for Crawl-delay: 10 and we obey it
    "moltke.nccu.edu.tw": HostPolicy(0.5, 2),    # 0.5 s is the pace used to download the forms before, and each form has its own cookie jar, so two in flight is safe
    "cpbae.nccu.edu.tw": HostPolicy(5.0, 1),     # tentative: this host throttles heavily when hit quickly, so it starts slow and one at a time
}


def host_policy(host: str) -> HostPolicy:
    return HOST_POLICY.get(host.lower(), DEFAULT_POLICY)


# A parent unit named in the question (教務處 or 學生事務處) is registered with its site's home page, which lists no staff.
# So it reads this many of the sibling staff pages per batch and stops at the first batch with contacts parsed from a page.
# 3 is a choice, not a measurement. The rate limiter above still decides how fast the requests go out.
PARENT_BATCH_SIZE = _env_int("LIVE_PARENT_BATCH_SIZE", 3)


# A live page whose normalized text is shorter than this fraction of the snapshot's is treated as an incomplete static
# render, such as a page built by JavaScript, and not as an edit. This is an estimate.
# One JavaScript-built page (oic) came back with 37 characters against 4956 in the snapshot.
INCOMPLETE_RATIO = _env_float("LIVE_INCOMPLETE_RATIO", 0.5)

# --- prefetch -----------------------------------------------------------------------------------------------
PREFETCH_TTL_SECONDS = _env_float("LIVE_PREFETCH_TTL", 120.0)   # a prefetched result is reused for this long (freshness, not a budget)
PREFETCH_WORKERS = _env_int("LIVE_PREFETCH_WORKERS", 16)        # sleeping in the rate limiter is cheap, and this must exceed the pages one chain waits on

# --- circuit breaker --------------------------------------------------------------------------
# After this many failures in a row on one host, the host is paused for the cooldown.
# Questions during the pause use the snapshot for that host, marked as a fallback.
BREAKER_THRESHOLD = _env_int("LIVE_BREAKER_THRESHOLD", 5)
BREAKER_COOLDOWN = _env_float("LIVE_BREAKER_COOLDOWN", 300.0)

# --- cache of live results (the lifetimes are estimates, to be tuned after measuring) ------------
CACHE_DIR = ROOT / "rag" / "live" / "_cache"
CACHE_DB = CACHE_DIR / "live.sqlite"
TTL_SECONDS = {
    "page": _env_int("LIVE_TTL_PAGE", 600),
    "listing": _env_int("LIVE_TTL_LISTING", 300),
    "contact": _env_int("LIVE_TTL_CONTACT", 3600),
    "form": _env_int("LIVE_TTL_FORM", 3600),
    "pdf": _env_int("LIVE_TTL_PDF", 86400),
}

# --- slow-question notices: they only warn and never abort anything ---------------------------
def _env_seconds(name: str, default: tuple[float, ...]) -> tuple[float, ...]:
    """A comma-separated list of positive seconds ("120,300"), ascending. Anything unusable falls back to the default."""
    try:
        vals = sorted({float(x) for x in os.environ[name].split(",") if x.strip()})
    except (KeyError, ValueError):
        return default
    return tuple(vals) if vals and vals[0] > 0 else default


# A live question normally takes 70-220 s, and the progress list already shows what is happening.
# So only an unusually long wait is worth a notice. Thresholds of 30 and 60 s would fire on normal runs.
SLOW_WARN_SECONDS = _env_seconds("LIVE_SLOW_WARN_SECONDS", (120, 300))
