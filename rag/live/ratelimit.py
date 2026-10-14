"""
rag/live/ratelimit.py
Per-host pacing + per-host concurrency + global concurrency + circuit breaker (§5.5, §5.4).

"Concurrency" is how many requests are in flight at once; "interval" is the minimum gap between
request *starts* to one host. A slot is reserved by time before it waits, so a 10-second Crawl-delay
host (osa) queues its own callers without holding a global slot while it sleeps.
Clock and sleep are injectable so tests run in zero real time.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

from rag.live import config


class RateLimiter:
    def __init__(self, global_concurrency: int | None = None, clock=time.monotonic, sleep=time.sleep):
        self._clock, self._sleep = clock, sleep
        self._global = threading.BoundedSemaphore(global_concurrency or config.GLOBAL_CONCURRENCY)
        self._lock = threading.Lock()
        self._host_sem: dict[str, threading.BoundedSemaphore] = {}
        self._next_start: dict[str, float] = {}
        self._fails: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def _sem(self, host: str) -> threading.BoundedSemaphore:
        with self._lock:
            if host not in self._host_sem:
                self._host_sem[host] = threading.BoundedSemaphore(config.host_policy(host).concurrency)
            return self._host_sem[host]

    @contextmanager
    def slot(self, host: str):
        """Hold while performing one request to `host`."""
        pol = config.host_policy(host)
        with self._sem(host):
            with self._lock:
                now = self._clock()
                start = max(now, self._next_start.get(host, 0.0))
                self._next_start[host] = start + pol.min_interval
            if start > now:
                self._sleep(start - now)
            with self._global:
                yield

    def penalize(self, host: str, seconds: float) -> None:
        """Server said Retry-After: push this host's next start out."""
        with self._lock:
            self._next_start[host] = max(self._next_start.get(host, 0.0), self._clock() + seconds)

    # --- circuit breaker ---------------------------------------------------------------------
    def breaker_open(self, host: str) -> bool:
        with self._lock:
            until = self._open_until.get(host)
            if until is None:
                return False
            if self._clock() >= until:        # cooldown over: half-open, allow a probe
                del self._open_until[host]
                self._fails[host] = config.BREAKER_THRESHOLD - 1
                return False
            return True

    def record_success(self, host: str) -> None:
        with self._lock:
            self._fails[host] = 0

    def record_failure(self, host: str) -> None:
        with self._lock:
            self._fails[host] = self._fails.get(host, 0) + 1
            if self._fails[host] >= config.BREAKER_THRESHOLD:
                self._open_until[host] = self._clock() + config.BREAKER_COOLDOWN
