"""
rag/live/schedule.py
Which page should the browser render next? (docs/phase_j_live_fetch_plan.md, P4 step 3)

The browser-owner thread renders one page at a time and the rate limiter enforces a minimum gap between requests to the
same host (osa.nccu.edu.tw: 10 s, from its robots.txt Crawl-delay). Rendering a host's pages back to back would leave the
browser asleep inside the limiter; this scheduler feeds the owner ONE page at a time, choosing each time from the real
state of the limiter:

  * the host with the longest remaining chain (pages left x its interval) is the critical path: its pages must start as
    early as possible, and the other hosts' pages fill the waiting gaps between them;
  * a filler page is dispatched only if it is expected to FINISH before the critical host is ready again -- otherwise
    waiting a second or two for the critical host loses less than letting a 3 s filler push it back (a greedy
    "anything ready goes" version started osa's pages at 0/12/24/34 s instead of 0/10/20/30 in the simulation);
  * if nobody is ready, the page that becomes ready soonest; ties keep the caller's order.

"Expected to finish" needs a render-time estimate. Real page times are not well known (P0: 2.5-3.4 s on nine staff pages;
the 2026-08-25 index crawl: 6.4 s per URL on average), so the estimate starts at config.RENDER_ESTIMATE_SECONDS and, as
pages finish, becomes the running mean of the real ones. A wrong estimate costs a little idle time, never correctness:
the rate limiter still enforces every gap.

`run(urls)` returns {url: Future[RenderResult]} at once; results arrive as pages finish, so callers can use
`as_completed`. Future callbacks run on the dispatcher thread -- they must hand real work to a pool, not do it inline,
or they would delay the next dispatch. This is the simultaneous-crawling hook for P4.5 too: only `_choose` and the
dispatch loop would change.

NOTE (2026-10-16, P4 H7): NOT USED by the production path any more. Staff pages are now fetched with httpx first (a thread pool
plus the rate limiter, rag/live/contacts.py), so there is no longer a single browser queue whose order needs choosing; only the
rare escalated page goes to the browser. Kept (with its tests) as the starting point for P4.5 (simultaneous crawling), which is
deferred; delete this module and test_live_p4_schedule.py if P4.5 is dropped. RateLimiter.wait_time exists only for this module.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future
from typing import Callable

from rag.live import config
from rag.live.allowlist import host_of
from rag.live.browser import RenderResult
from rag.live.ratelimit import RateLimiter

log = logging.getLogger("rag.live")


class RenderScheduler:
    def __init__(self, submit: Callable[[str], "Future[RenderResult]"], limiter: RateLimiter):
        self._submit = submit              # normally BrowserOwner.render
        self._limiter = limiter
        self.order: list[str] = []         # dispatch order of the last run(), for logs and tests
        self._seen: list[float] = []       # render times of pages that succeeded, to refine the estimate

    @property
    def estimate(self) -> float:
        return sum(self._seen) / len(self._seen) if self._seen else config.RENDER_ESTIMATE_SECONDS

    def run(self, urls: list[str]) -> dict[str, "Future[RenderResult]"]:
        urls = list(dict.fromkeys(urls))   # same URL asked twice -> rendered once
        futures: dict[str, Future] = {u: Future() for u in urls}
        self.order = []
        if urls:
            threading.Thread(target=self._dispatch, args=(urls, futures), name="render-scheduler", daemon=True).start()
        return futures

    # --- internals ----------------------------------------------------------------------------------------------
    def _choose(self, remaining: list[str]) -> str:
        left: dict[str, int] = {}
        for u in remaining:
            left[host_of(u)] = left.get(host_of(u), 0) + 1

        def chain(u: str) -> float:        # time the host still needs, ignoring render time
            h = host_of(u)
            return left[h] * config.host_policy(h).min_interval

        index = {u: i for i, u in enumerate(remaining)}
        wait = {u: self._limiter.wait_time(host_of(u)) for u in remaining}
        critical = min(remaining, key=lambda u: (-chain(u), index[u]))           # next page of the bottleneck host
        if wait[critical] <= 1e-9:
            return critical
        fillers = [u for u in remaining if wait[u] <= 1e-9 and host_of(u) != host_of(critical)]
        if fillers and self.estimate <= wait[critical]:
            return min(fillers, key=lambda u: (-chain(u), index[u]))             # fits inside the gap
        if fillers and wait[critical] > 0:
            return critical                                                      # shorter to wait than to delay it
        return min(remaining, key=lambda u: (wait[u], -chain(u), index[u]))

    def _dispatch(self, urls: list[str], futures: dict[str, Future]) -> None:
        remaining = list(urls)
        while remaining:
            url = self._choose(remaining)
            remaining.remove(url)
            self.order.append(url)
            try:
                res = self._submit(url).result()
            except BaseException as e:      # noqa: BLE001 -- failure is data, and one page must not strand the rest
                log.warning("render of %s raised %s: %s", url, type(e).__name__, e)
                res = RenderResult(url, error="render_error", detail=f"{type(e).__name__}: {e}"[:200])
            if res.ok and res.elapsed > 0:
                self._seen.append(res.elapsed)
            futures[url].set_result(res)
