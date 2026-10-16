"""
Offline tests for rag/live/schedule.py (P4 step 3) on a FAKE CLOCK: no Chromium, no network, no LLM, and no real
sleeping. A fake "owner" advances the shared clock the way the real one would (wait inside the rate limiter, then spend
the render time), so total times in these tests are simulated seconds, not measurements.
    python -W ignore -m unittest experiments.live_spikes.test_live_p4_schedule -v
"""

from __future__ import annotations

import sys
import threading
import unittest
from concurrent.futures import Future, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rag.live.allowlist import host_of  # noqa: E402
from rag.live.browser import BrowserOwner, RenderResult  # noqa: E402
from rag.live.ratelimit import RateLimiter  # noqa: E402
from rag.live.schedule import RenderScheduler  # noqa: E402


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeOwner:
    """Serial, like the real owner: honours the limiter (sleeping on the fake clock), then spends `render_s`."""

    def __init__(self, clock: FakeClock, limiter: RateLimiter, render_s=3.0, fail=()):
        self.clock, self.limiter, self.render_s, self.fail = clock, limiter, render_s, set(fail)
        self.log: list[tuple[str, float, float]] = []      # (url, start, end)

    def render(self, url: str) -> Future:
        fut: Future = Future()
        with self.limiter.slot(host_of(url)):
            start = self.clock.t
            self.clock.t += self.render_s
        self.log.append((url, start, self.clock.t))
        fut.set_result(RenderResult(url, error="boom") if url in self.fail
                       else RenderResult(url, ok=True, html=b"x", status=200, elapsed=self.render_s))
        return fut


OSA = [f"https://osa.nccu.edu.tw/tw/p{i}" for i in range(4)]
OTHERS = ["https://aca.nccu.edu.tw/zh/a", "https://aca.nccu.edu.tw/zh/b", "https://aca.nccu.edu.tw/zh/c",
          "https://cashier.nccu.edu.tw/PageStaffing?fid=1", "https://www.lib.nccu.edu.tw/p/1", "https://oic.nccu.edu.tw/Category/596"]


def rig(render_s=3.0, fail=()):
    clock = FakeClock()
    limiter = RateLimiter(clock=clock.now, sleep=clock.sleep)
    owner = FakeOwner(clock, limiter, render_s, fail)
    return clock, limiter, owner


def run_all(sched: RenderScheduler, urls):
    futs = sched.run(urls)
    return {u: f.result(10) for u, f in futs.items()}


class TestScheduler(unittest.TestCase):
    def test_osa_pages_start_first_and_the_others_fill_its_ten_second_gaps(self):
        clock, limiter, owner = rig()
        sched = RenderScheduler(owner.render, limiter)
        run_all(sched, OTHERS + OSA)                           # caller lists the slow host LAST
        starts = {u: s for u, s, e in owner.log}
        self.assertEqual([starts[u] for u in OSA], [0.0, 10.0, 20.0, 30.0])      # osa never waits longer than its gap
        self.assertTrue(sched.order[0] in OSA)
        self.assertLessEqual(clock.t, 33.5)                    # osa's own floor: 3 gaps of 10 s + the last render

    def test_a_wrong_starting_estimate_is_corrected_by_what_the_pages_really_take(self):
        """Pages really take 6 s but the scheduler starts out believing 3 s: after seeing real renders it must stop
        squeezing fillers into gaps they do not fit, so osa still starts every 10 s."""
        clock, limiter, owner = rig(render_s=6.0)
        sched = RenderScheduler(owner.render, limiter)
        run_all(sched, OTHERS + OSA)
        starts = {u: s for u, s, e in owner.log}
        self.assertEqual([starts[u] for u in OSA], [0.0, 10.0, 20.0, 30.0])
        self.assertAlmostEqual(sched.estimate, 6.0)

    def test_naive_fifo_order_is_much_slower_on_the_same_pages(self):
        clock, limiter, owner = rig()
        for u in OTHERS + OSA:                                 # no scheduler: just submit in the caller's order
            owner.render(u).result()
        self.assertGreater(clock.t, 45.0)                      # 6 pages x 3 s, THEN osa's 33 s chain

    def test_scheduler_saves_time_over_fifo_by_the_amount_it_claims(self):
        c1, l1, o1 = rig()
        for u in OTHERS + OSA:
            o1.render(u).result()
        c2, l2, o2 = rig()
        run_all(RenderScheduler(o2.render, l2), OTHERS + OSA)
        self.assertGreaterEqual(c1.t - c2.t, 10.0)

    def test_when_the_next_osa_page_is_not_ready_another_hosts_page_is_rendered_instead(self):
        clock, limiter, owner = rig()
        sched = RenderScheduler(owner.render, limiter)
        run_all(sched, OSA + OTHERS)
        hosts = [host_of(u) for u in sched.order]
        # after the first osa page, the next dispatch must be a non-osa page (osa still has ~7 s to wait)
        self.assertEqual(hosts[0], "osa.nccu.edu.tw")
        self.assertNotEqual(hosts[1], "osa.nccu.edu.tw")

    def test_a_single_host_keeps_the_callers_order(self):
        clock, limiter, owner = rig()
        sched = RenderScheduler(owner.render, limiter)
        urls = [f"https://aca.nccu.edu.tw/zh/{c}" for c in "dcba"]
        run_all(sched, urls)
        self.assertEqual(sched.order, urls)

    def test_ties_keep_the_callers_order(self):
        clock, limiter, owner = rig()
        sched = RenderScheduler(owner.render, limiter)
        urls = ["https://aca.nccu.edu.tw/zh/1", "https://cashier.nccu.edu.tw/p", "https://www.lib.nccu.edu.tw/p"]
        run_all(sched, urls)
        self.assertEqual(sched.order, urls)

    def test_duplicate_urls_are_rendered_once(self):
        clock, limiter, owner = rig()
        sched = RenderScheduler(owner.render, limiter)
        out = run_all(sched, [OTHERS[0], OTHERS[0], OTHERS[1]])
        self.assertEqual(len(owner.log), 2)
        self.assertEqual(len(out), 2)

    def test_a_failed_render_is_data_and_the_rest_still_run(self):
        clock, limiter, owner = rig(fail={OTHERS[0]})
        out = run_all(RenderScheduler(owner.render, limiter), OTHERS[:3])
        self.assertFalse(out[OTHERS[0]].ok)
        self.assertTrue(out[OTHERS[1]].ok and out[OTHERS[2]].ok)

    def test_an_owner_that_raises_does_not_strand_the_other_pages(self):
        clock, limiter, owner = rig()

        def bad(url):
            if url == OTHERS[0]:
                raise RuntimeError("queue closed")
            return owner.render(url)
        out = run_all(RenderScheduler(bad, limiter), OTHERS[:2])
        self.assertEqual(out[OTHERS[0]].error, "render_error")
        self.assertTrue(out[OTHERS[1]].ok)

    def test_empty_input(self):
        clock, limiter, owner = rig()
        self.assertEqual(RenderScheduler(owner.render, limiter).run([]), {})

    def test_results_can_be_consumed_in_completion_order(self):
        clock, limiter, owner = rig()
        futs = RenderScheduler(owner.render, limiter).run(OTHERS[:3])
        seen = [f.result().url for f in as_completed(futs.values(), timeout=10)]
        self.assertEqual(sorted(seen), sorted(OTHERS[:3]))

    def test_the_chain_rule_picks_the_host_with_more_waiting_ahead(self):
        clock, limiter, owner = rig()
        sched = RenderScheduler(owner.render, limiter)
        # 2 osa pages (1 gap of 10 s) vs 3 aca pages (2 gaps of 1 s): osa is the longer chain
        run_all(sched, [OTHERS[0], OTHERS[1], OTHERS[2], OSA[0], OSA[1]])
        self.assertEqual(host_of(sched.order[0]), "osa.nccu.edu.tw")


class TestLimiterWaitTime(unittest.TestCase):
    def test_wait_time_does_not_reserve_and_counts_down(self):
        clock = FakeClock()
        lim = RateLimiter(clock=clock.now, sleep=clock.sleep)
        self.assertEqual(lim.wait_time("osa.nccu.edu.tw"), 0.0)
        with lim.slot("osa.nccu.edu.tw"):
            pass
        self.assertEqual(lim.wait_time("osa.nccu.edu.tw"), 10.0)
        self.assertEqual(lim.wait_time("osa.nccu.edu.tw"), 10.0)     # asking twice changed nothing
        clock.t += 4
        self.assertEqual(lim.wait_time("osa.nccu.edu.tw"), 6.0)
        self.assertEqual(lim.wait_time("aca.nccu.edu.tw"), 0.0)


class TestOwnerAroundHook(unittest.TestCase):
    def test_the_slot_is_held_around_every_render_on_the_owner_thread(self):
        events: list = []

        class Backend:
            def start(self): pass
            def stop(self): pass
            def render(self, url):
                events.append(("render", url, threading.get_ident()))
                return RenderResult(url, ok=True)

        class Around:
            def __init__(self, url): self.url = url
            def __enter__(self): events.append(("enter", self.url, threading.get_ident()))
            def __exit__(self, *a): events.append(("exit", self.url, threading.get_ident()))
        o = BrowserOwner(Backend, around=Around)
        try:
            o.render("https://aca.nccu.edu.tw/a").result(5)
        finally:
            o.shutdown()
        self.assertEqual([e[0] for e in events], ["enter", "render", "exit"])
        self.assertEqual(len({e[2] for e in events}), 1)             # all on the owner thread


if __name__ == "__main__":
    unittest.main(verbosity=2)
