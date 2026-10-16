"""
Offline tests for rag/live/browser.py (P4 step 1). The owner's logic is exercised with a FAKE backend -- no Chromium,
no network, no LLM. A final class does a real-Chromium LIFECYCLE smoke test (start/stop/idle/restart, no leftover
processes) on a local page; nothing is sent to nccu.edu.tw.
    python -W ignore -m unittest experiments.live_spikes.test_live_p4_browser -v
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rag.live.browser import BrowserCrashed, BrowserOwner, PlaywrightBackend, RenderResult  # noqa: E402


class FakeBackend:
    """Records which thread touched it, whether calls overlapped, and can be told to misbehave."""
    instances: list["FakeBackend"] = []
    script: list = []                 # per-render behaviours consumed in order: "ok"|"crash"|"boom"
    start_fails = 0
    delay = 0.0

    def __init__(self):
        self.threads: set[int] = set()
        self.started = self.stopped = 0
        self._active = 0
        self.max_active = 0
        FakeBackend.instances.append(self)

    def start(self):
        self.threads.add(threading.get_ident())
        if FakeBackend.start_fails > 0:
            FakeBackend.start_fails -= 1
            raise RuntimeError("chromium missing")
        self.started += 1

    def render(self, url):
        self.threads.add(threading.get_ident())
        self._active += 1
        self.max_active = max(self.max_active, self._active)
        try:
            if FakeBackend.delay:
                time.sleep(FakeBackend.delay)
            step = FakeBackend.script.pop(0) if FakeBackend.script else "ok"
            if step == "crash":
                raise BrowserCrashed("target closed")
            if step == "boom":
                raise ValueError("page exploded")
            return RenderResult(url, ok=True, html=f"<p>{url}</p>".encode(), status=200)
        finally:
            self._active -= 1

    def stop(self):
        self.threads.add(threading.get_ident())
        self.stopped += 1


def fresh_owner(**kw) -> BrowserOwner:
    FakeBackend.instances, FakeBackend.script, FakeBackend.start_fails, FakeBackend.delay = [], [], 0, 0.0
    return BrowserOwner(FakeBackend, **kw)


class TestOwnerLogic(unittest.TestCase):
    def test_nothing_starts_until_the_first_request(self):
        o = fresh_owner()
        self.assertIsNone(o._thread)
        self.assertEqual(FakeBackend.instances, [])
        o.shutdown()

    def test_render_returns_a_future_that_resolves(self):
        o = fresh_owner()
        try:
            fut = o.render("http://x/1")
            r = fut.result(5)
            self.assertTrue(r.ok)
            self.assertEqual(r.html, b"<p>http://x/1</p>")
        finally:
            o.shutdown()

    def test_every_backend_call_happens_on_one_thread_whoever_calls(self):
        o = fresh_owner()
        try:
            futs, lock = [], threading.Lock()

            def caller(i):
                f = o.render(f"http://x/{i}")
                with lock:
                    futs.append(f)
            ts = [threading.Thread(target=caller, args=(i,)) for i in range(8)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            self.assertTrue(all(f.result(5).ok for f in futs))
            self.assertEqual(len(FakeBackend.instances[0].threads), 1)
            self.assertEqual(FakeBackend.instances[0].threads, {o.thread_ident})
            self.assertNotIn(threading.get_ident(), FakeBackend.instances[0].threads)
        finally:
            o.shutdown()

    def test_requests_never_overlap_and_keep_arrival_order(self):
        o = fresh_owner()
        FakeBackend.delay = 0.02
        try:
            futs = [o.render(f"http://x/{i}") for i in range(6)]
            done = [f.result(10).url for f in futs]
            self.assertEqual(done, [f"http://x/{i}" for i in range(6)])
            self.assertEqual(FakeBackend.instances[0].max_active, 1)
        finally:
            o.shutdown()

    def test_as_completed_hands_back_results_as_they_finish(self):
        o = fresh_owner()
        try:
            futs = [o.render(f"http://x/{i}") for i in range(3)]
            self.assertEqual(sorted(f.result().url for f in as_completed(futs, timeout=5)), [f"http://x/{i}" for i in range(3)])
        finally:
            o.shutdown()

    def test_idle_closes_the_browser_and_the_next_request_restarts_it_on_the_same_thread(self):
        o = fresh_owner(idle_seconds=0.15)
        try:
            self.assertTrue(o.render("http://x/1").result(5).ok)
            b = FakeBackend.instances[0]
            deadline = time.monotonic() + 3
            while b.stopped == 0 and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(b.stopped, 1)                      # closed while idle
            self.assertTrue(o.render("http://x/2").result(5).ok)
            self.assertEqual(len(FakeBackend.instances), 2)     # a fresh backend was started
            self.assertEqual(FakeBackend.instances[1].threads, {o.thread_ident})
        finally:
            o.shutdown()

    def test_a_crash_restarts_once_and_retries(self):
        o = fresh_owner()
        FakeBackend.script = ["crash"]
        try:
            r = o.render("http://x/1").result(5)
            self.assertTrue(r.ok)
            self.assertEqual(len(FakeBackend.instances), 2)
            self.assertEqual(FakeBackend.instances[0].stopped, 1)
        finally:
            o.shutdown()

    def test_two_crashes_in_a_row_is_an_error_result_not_an_exception(self):
        o = fresh_owner()
        FakeBackend.script = ["crash", "crash"]
        try:
            r = o.render("http://x/1").result(5)
            self.assertEqual((r.ok, r.error), (False, "crashed"))
            self.assertTrue(o.render("http://x/2").result(5).ok)   # the owner survives and recovers
        finally:
            o.shutdown()

    def test_start_failure_is_an_error_result_and_the_next_request_tries_again(self):
        o = fresh_owner()
        FakeBackend.start_fails = 1
        try:
            r = o.render("http://x/1").result(5)
            self.assertEqual((r.ok, r.error), (False, "start_failed"))
            self.assertIn("chromium missing", r.detail)
            self.assertTrue(o.render("http://x/2").result(5).ok)
        finally:
            o.shutdown()

    def test_a_page_error_keeps_the_browser(self):
        o = fresh_owner()
        FakeBackend.script = ["boom"]
        try:
            r = o.render("http://x/1").result(5)
            self.assertEqual((r.ok, r.error), (False, "render_error"))
            self.assertTrue(o.render("http://x/2").result(5).ok)
            self.assertEqual(len(FakeBackend.instances), 1)     # no restart for a mere page error
        finally:
            o.shutdown()

    def test_shutdown_stops_the_browser_resolves_pending_and_refuses_new_work(self):
        o = fresh_owner()
        FakeBackend.delay = 0.1
        first = o.render("http://x/1")
        queued = [o.render(f"http://x/{i}") for i in range(2, 5)]
        o.shutdown()
        self.assertTrue(first.result(5).ok or first.result(5).error == "closed")
        self.assertTrue(all(f.result(5).error in ("", "closed") for f in queued))
        self.assertEqual(FakeBackend.instances[0].stopped, 1)
        self.assertFalse(o._thread.is_alive())
        late = o.render("http://x/9").result(5)
        self.assertEqual((late.ok, late.error), (False, "closed"))
        o.shutdown()                                            # idempotent

    def test_get_owner_registers_one_atexit_hook_and_reuses_the_instance(self):
        from unittest import mock
        import rag.live.browser as b
        b._owner = None
        with mock.patch.object(b.atexit, "register") as reg:
            a, c = b.get_owner(), b.get_owner()
        self.assertIs(a, c)
        reg.assert_called_once_with(a.shutdown)
        b._owner = None


def chromium_processes() -> int:
    out = subprocess.run(["ps", "-eo", "comm"], capture_output=True, text=True).stdout
    return sum(1 for l in out.splitlines() if "chrom" in l.lower() or "headless_shell" in l.lower())


class TestRealChromiumLifecycle(unittest.TestCase):
    """Real Chromium, local only. Lifecycle, not rendering (rendering is step 2)."""

    def test_start_stop_idle_and_restart_leave_no_processes_behind(self):
        before = chromium_processes()
        started: list[PlaywrightBackend] = []

        def factory():
            b = PlaywrightBackend()
            started.append(b)
            return b

        class Probe(PlaywrightBackend):
            def render(self, url):                      # step-1 stand-in: prove the browser is usable on this thread
                page = self.browser.new_page()
                page.set_content("<div id=x>hello 休學</div>")
                text = page.inner_text("#x")
                page.close()
                return RenderResult(url, ok=True, html=text.encode(), status=200)
        o = BrowserOwner(lambda: (started.append(Probe()) or started[-1]), idle_seconds=1.0)
        try:
            r1 = o.render("local:1").result(60)
            self.assertTrue(r1.ok, r1.detail)
            self.assertEqual(r1.html.decode(), "hello 休學")
            self.assertTrue(started[0].running)
            self.assertGreater(chromium_processes(), before)
            deadline = time.monotonic() + 15
            while started[0].browser is not None and time.monotonic() < deadline:
                time.sleep(0.2)
            self.assertIsNone(started[0].browser)       # idle -> closed
            r2 = o.render("local:2").result(60)         # restart on the same thread
            self.assertTrue(r2.ok, r2.detail)
            self.assertEqual(len(started), 2)
        finally:
            o.shutdown()
        time.sleep(1.0)
        self.assertEqual(chromium_processes(), before)  # nothing left running


if __name__ == "__main__":
    unittest.main(verbosity=2)
