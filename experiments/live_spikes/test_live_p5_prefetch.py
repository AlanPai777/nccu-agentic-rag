"""
Offline tests for rag/live/prefetch.py (P5): the chain page -> forms -> offices -> staff pages is started from the SNAPSHOT before the
real chain asks, and the real chain then reuses it. Fake network / browser / forms; no Chromium, no real site, no LLM.
    python -W ignore -m unittest experiments.live_spikes.test_live_p5_prefetch -v
"""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import p4_fakes as fk  # noqa: E402
import test_live_p4_contacts as tc  # noqa: E402
import rag.agentic.tools.form as form_tool  # noqa: E402
import rag.agentic.tools.page as page_tool  # noqa: E402
from rag.live import hook, prefetch as pf  # noqa: E402
from rag.live.contacts import fetch_contact_pages, process_page  # noqa: E402

PAGE = "https://aca.nccu.edu.tw/zh/x"
SNAP_PAGE = {"url": PAGE, "title": "休學", "text": "表單 QP-T01-02-05 與 QP-T01-03-02", "subdomain": "aca"}


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class FakeDeps(pf.Deps):
    """Records what the chain did and when; every step can be made to wait for an Event."""

    def __init__(self, ids=("QP-A", "QP-B"), offices=("註冊組",), pages=None, gate_snapshot=None, gate_page=None, boom=None):
        self.ids, self.offices, self.pages = list(ids), list(offices), pages or {}
        self.gate_snapshot, self.gate_page, self.boom = gate_snapshot, gate_page, boom or {}
        self.log: list[tuple[str, str]] = []
        self.lock = threading.Lock()

    def _rec(self, what, key):
        with self.lock:
            self.log.append((what, key))

    def extract_form_ids(self, text):
        if "extract" in self.boom:
            raise RuntimeError("boom")
        return list(self.ids)

    def form_snapshot(self, form_id):
        self._rec("snapshot_start", form_id)
        if self.gate_snapshot is not None:
            self.gate_snapshot.wait(5)
        if "snapshot" in self.boom:
            raise RuntimeError("grep exploded")
        return {"form_id": form_id, "form_title": f"T{form_id}", "text": f"{form_id} 教務處註冊組", "url": f"u/{form_id}"}

    def live_form(self, form_id, snapshot_provider):
        self._rec("live_form_start", form_id)
        snap = snapshot_provider()
        self._rec("live_form_done", form_id)
        return {**snap, "live_marker": f"[marker {form_id}]"}

    def detect_offices(self, text):
        self._rec("detect_offices", text[:20])
        return list(self.offices)

    def plan_pages(self, offices):
        return self.pages, []

    def process_page(self, url, info):
        self._rec("process_page_start", url)
        if self.gate_page is not None:
            self.gate_page.wait(5)
        return process_page_fake(url, info)


def process_page_fake(url, info):
    from rag.live.contacts import PageOutcome
    return PageOutcome(url=url, offices=info["offices"], state="live_same", text="t", snapshot_text="t", snapshot_at="2026-08-25",
                       checked="x", handled=[{"name": "n", "ext": "1"}])


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.store = pf.PrefetchStore(ttl=60)

    def tearDown(self):
        self.store.shutdown(wait=True)

    def settle(self, deps, what, n):
        self.assertTrue(wait_for(lambda: sum(1 for w, _ in deps.log if w == what) >= n), f"{what} x{n} never happened: {deps.log}")


class TestTheChain(StoreCase):
    def test_the_live_form_fetches_start_immediately_without_waiting_for_the_snapshot_lookup(self):
        gate = threading.Event()
        deps = FakeDeps(gate_snapshot=gate)
        self.assertTrue(pf.maybe_start(PAGE, SNAP_PAGE, self.store, deps, force=True))
        self.settle(deps, "live_form_start", 2)                              # both forms are being fetched live...
        self.assertEqual([w for w, _ in deps.log if w == "live_form_done"], [])  # ...while the local lookup is still blocked
        gate.set()
        self.settle(deps, "live_form_done", 2)

    def test_offices_come_from_the_snapshot_form_text_and_their_pages_start_before_anyone_asks(self):
        url = "https://aca.nccu.edu.tw/zh/人員職掌-註冊"
        deps = FakeDeps(offices=["註冊組"], pages={url: {"offices": ["註冊組"], "snapshot_text": "s", "snapshot_at": "2026-08-25"}})
        pf.maybe_start(PAGE, SNAP_PAGE, self.store, deps, force=True)
        self.settle(deps, "process_page_start", 1)
        detect = next(k for w, k in deps.log if w == "detect_offices")
        self.assertIn("教務處註冊組", detect)                                   # fed with the forms' snapshot text
        self.assertEqual([k for w, k in deps.log if w == "process_page_start"], [url])

    def test_one_chain_per_page_within_the_ttl(self):
        deps = FakeDeps()
        self.assertTrue(pf.maybe_start(PAGE, SNAP_PAGE, self.store, deps, force=True))
        self.assertFalse(pf.maybe_start(PAGE, SNAP_PAGE, self.store, deps, force=True))

    def test_a_page_can_be_prefetched_again_after_the_ttl(self):
        now = [0.0]
        store = pf.PrefetchStore(ttl=10, clock=lambda: now[0])
        deps = FakeDeps()
        try:
            self.assertTrue(pf.maybe_start(PAGE, SNAP_PAGE, store, deps, force=True))
            now[0] += 11
            self.assertTrue(pf.maybe_start(PAGE, SNAP_PAGE, store, deps, force=True))
        finally:
            store.shutdown()


class TestWhenItStarts(StoreCase):
    def test_nothing_starts_unless_both_flags_are_on(self):
        deps = FakeDeps()
        for env in ({}, {"LIVE_FETCH": "on"}, {"LIVE_PREFETCH": "on"}, {"LIVE_FETCH": "off", "LIVE_PREFETCH": "on"}):
            with self.subTest(env), mock.patch.dict(os.environ, env, clear=False):
                os.environ.pop("LIVE_FETCH", None) if "LIVE_FETCH" not in env else None
                os.environ.pop("LIVE_PREFETCH", None) if "LIVE_PREFETCH" not in env else None
                self.assertFalse(pf.maybe_start(PAGE, SNAP_PAGE, self.store, deps))
        with mock.patch.dict(os.environ, {"LIVE_FETCH": "on", "LIVE_PREFETCH": "on"}):
            self.assertTrue(pf.maybe_start(PAGE, SNAP_PAGE, self.store, deps))

    def test_a_page_with_no_form_ids_or_not_in_the_snapshot_starts_nothing(self):
        self.assertFalse(pf.maybe_start(PAGE, SNAP_PAGE, self.store, FakeDeps(ids=[]), force=True))
        self.assertFalse(pf.maybe_start(PAGE, {"error": "URL not found"}, self.store, FakeDeps(), force=True))

    def test_get_page_tool_starts_it_after_the_local_read_and_before_the_live_check(self):
        order = []
        with mock.patch.object(page_tool, "_get_page_raw", lambda *a, **k: order.append("snapshot read") or dict(SNAP_PAGE)), \
                mock.patch.object(page_tool, "start_prefetch", lambda *a, **k: order.append("prefetch")), \
                mock.patch.object(page_tool, "apply_page", lambda u, p, live=None: order.append("live check") or p), \
                mock.patch.object(page_tool, "_detect_offices", lambda t: []):
            page_tool.get_page_tool.func(PAGE, {"subdomain_hint": None})
        self.assertEqual(order, ["snapshot read", "prefetch", "live check"])


class TestRealChainReusesIt(StoreCase):
    def _tool_counts(self):
        counts = {"raw": [], "apply": []}

        def raw(fid):
            counts["raw"].append(fid)
            return {"form_id": fid, "form_title": f"T{fid}", "text": "snap", "url": "u"}

        def apply(fid, snap, live=None):
            counts["apply"].append(fid)
            snap = snap() if callable(snap) else snap
            return {**snap, "live_marker": f"[live:src status=live_same kind=form checked=x snap=x tls=0 url=u/{fid}]"}
        return counts, raw, apply

    def test_get_form_tool_uses_what_the_prefetch_already_did(self):
        counts, raw, apply = self._tool_counts()

        class D(FakeDeps):
            def form_snapshot(s, fid):
                return raw(fid)

            def live_form(s, fid, provider):
                return apply(fid, provider)
        deps = D(ids=["QP-A"], offices=[])
        with mock.patch.object(form_tool, "get_store", lambda: self.store), \
                mock.patch.object(form_tool, "_get_form_raw", raw), mock.patch.object(form_tool, "apply_form", apply):
            pf.maybe_start(PAGE, SNAP_PAGE, self.store, deps, force=True)
            self.assertTrue(wait_for(lambda: counts["apply"] == ["QP-A"]))
            out = form_tool.get_form_tool.func("QP-A", {})
        self.assertEqual((counts["raw"], counts["apply"]), (["QP-A"], ["QP-A"]))   # once each: the tool did NOT redo them
        self.assertIn("TQP-A", out)
        self.assertIn("kind=form", out)

    def test_without_a_prefetch_the_tool_does_exactly_what_it_always_did(self):
        counts, raw, apply = self._tool_counts()
        with mock.patch.object(form_tool, "get_store", lambda: self.store), \
                mock.patch.object(form_tool, "_get_form_raw", raw), mock.patch.object(form_tool, "apply_form", apply):
            form_tool.get_form_tool.func("QP-A", {})
            form_tool.get_form_tool.func("QP-A", {})
        self.assertEqual((counts["raw"], counts["apply"]), (["QP-A"] * 2, ["QP-A"] * 2))   # nothing stored, nothing reused

    def test_a_form_the_prefetch_did_not_predict_is_fetched_normally(self):
        counts, raw, apply = self._tool_counts()

        class D(FakeDeps):
            def form_snapshot(s, fid):
                return raw(fid)

            def live_form(s, fid, provider):
                return apply(fid, provider)
        with mock.patch.object(form_tool, "get_store", lambda: self.store), \
                mock.patch.object(form_tool, "_get_form_raw", raw), mock.patch.object(form_tool, "apply_form", apply):
            pf.maybe_start(PAGE, SNAP_PAGE, self.store, D(ids=["QP-A"], offices=[]), force=True)
            self.assertTrue(wait_for(lambda: counts["apply"] == ["QP-A"]))
            form_tool.get_form_tool.func("QP-A", {})
            form_tool.get_form_tool.func("QP-NEW", {})                                   # the live page listed a form the snapshot did not
        self.assertEqual(sorted(counts["apply"]), ["QP-A", "QP-NEW"])

    def test_a_failed_prefetch_falls_back_to_doing_it_normally(self):
        counts, raw, apply = self._tool_counts()
        deps = FakeDeps(ids=["QP-A"], offices=[], boom={"snapshot": 1})
        with mock.patch.object(form_tool, "get_store", lambda: self.store), \
                mock.patch.object(form_tool, "_get_form_raw", raw), mock.patch.object(form_tool, "apply_form", apply):
            pf.maybe_start(PAGE, SNAP_PAGE, self.store, deps, force=True)
            self.assertTrue(wait_for(lambda: any(w == "snapshot_start" for w, _ in deps.log)))
            time.sleep(0.2)
            out = form_tool.get_form_tool.func("QP-A", {})
        self.assertEqual(counts["raw"], ["QP-A"])                                     # done normally, once
        self.assertIn("TQP-A", out)

    def test_an_expired_prefetch_is_not_reused(self):
        now = [0.0]
        store = pf.PrefetchStore(ttl=10, clock=lambda: now[0])
        try:
            store.submit("snap", "QP-A", lambda: "prefetched").result()
            self.assertEqual(store.form_snapshot("QP-A", lambda: "normal"), "prefetched")
            now[0] += 11
            self.assertEqual(store.form_snapshot("QP-A", lambda: "normal"), "normal")
        finally:
            store.shutdown()


class TestStaffPages(tc.Base):
    """The real process_page / fetch_contact_pages over the recorded staff pages."""

    def setUp(self):
        super().setUp()
        self.store = pf.PrefetchStore(ttl=60)
        self.static_log: list = []
        fetcher = fk.static_fetcher(self.static_pages(), log=self.static_log)
        self.render = fk.FakeRender(self.pages)
        self.fetch_static = lambda u: fetcher.fetch(u, kind="contact", use_cache=False)

    def tearDown(self):
        self.store.shutdown(wait=True)
        super().tearDown()

    def prefetch_all(self, offices, gate=None):
        pages, _ = tc.plan_pages(offices)

        class D(FakeDeps):
            def process_page(s, url, info):
                s._rec("process_page_start", url)
                if gate is not None:
                    gate.wait(5)
                return process_page(url, info, self_outer.fetch_static, self_outer.render)
        self_outer = self
        deps = D(ids=["QP-A"], offices=offices, pages=pages)
        pf.maybe_start(PAGE, SNAP_PAGE, self.store, deps, force=True)
        return deps, pages

    def test_pages_prefetched_are_not_fetched_again_by_contact_node(self):
        offices = ["註冊組", "出納組", "教務長室"]
        deps, pages = self.prefetch_all(offices)
        self.assertTrue(wait_for(lambda: len([1 for f in self.store._items.values() if f[1].done()]) >= 3 + 2))
        before = len(self.static_log)
        main_calls = []
        res = fetch_contact_pages(offices, lambda u: main_calls.append(u) or self.fetch_static(u), self.render, store=self.store)
        self.assertEqual(main_calls, [])                                   # no second fetch of any page
        self.assertEqual(len(self.static_log), before)
        self.assertEqual({o: res.pages[self.url(o)].state for o in offices},
                         {"註冊組": "live_changed", "出納組": "live_same", "教務長室": "live_changed"})

    def test_a_page_still_in_flight_is_waited_for_not_duplicated(self):
        gate = threading.Event()
        deps, _ = self.prefetch_all(["註冊組"], gate=gate)
        self.assertTrue(wait_for(lambda: any(w == "process_page_start" for w, _ in deps.log)))
        main_calls, out = [], {}
        t = threading.Thread(target=lambda: out.setdefault("r", fetch_contact_pages(
            ["註冊組"], lambda u: main_calls.append(u) or self.fetch_static(u), self.render, store=self.store)))
        t.start()
        time.sleep(0.2)
        self.assertTrue(t.is_alive())                                      # contact_node is waiting for the prefetch...
        gate.set()
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(main_calls, [])                                   # ...and did not fetch the page itself

    def test_the_prefetched_outcome_gets_the_office_names_of_the_real_request(self):
        deps, _ = self.prefetch_all(["註冊組"])
        self.assertTrue(wait_for(lambda: any(f[1].done() for k, f in self.store._items.items() if k[0] == "contact")))
        res = fetch_contact_pages(["註冊組"], self.fetch_static, self.render, store=self.store)
        self.assertEqual(res.pages[self.url("註冊組")].offices, ["註冊組"])

    def test_offices_the_prefetch_did_not_predict_are_fetched_normally(self):
        deps, _ = self.prefetch_all(["註冊組"])
        self.assertTrue(wait_for(lambda: any(f[1].done() for k, f in self.store._items.items() if k[0] == "contact")))
        main_calls = []
        res = fetch_contact_pages(["註冊組", "出納組"], lambda u: main_calls.append(u) or self.fetch_static(u), self.render,
                                  store=self.store)
        self.assertEqual(main_calls, [self.url("出納組")])                  # only the one the prefetch missed
        self.assertEqual(len(res.pages), 2)


class TestApplyFormProvider(unittest.TestCase):
    def test_the_live_fetch_runs_before_the_snapshot_provider_is_asked(self):
        order = []
        from rag.live.forms import FormLive
        fl = FormLive("QP-A", "link", ok=True, text="live text", title="t", fetched_at=time.time())
        with mock.patch.dict(os.environ, {"LIVE_FETCH": "on"}), \
                mock.patch("rag.live.forms.fetch_form", lambda fid, fetcher, **k: order.append("live fetch") or fl), \
                mock.patch.object(hook, "get_fetcher", lambda: None):
            out = hook.apply_form("QP-A", lambda: order.append("snapshot lookup") or {"form_id": "QP-A", "text": "live text", "form_title": "t"})
        self.assertEqual(order, ["live fetch", "snapshot lookup"])
        self.assertEqual(out["live_state"], "live_same")

    def test_off_mode_still_returns_the_snapshot_whether_given_directly_or_as_a_provider(self):
        with mock.patch.dict(os.environ, {"LIVE_FETCH": "off"}):
            d = {"form_id": "QP-A", "text": "x"}
            self.assertIs(hook.apply_form("QP-A", d), d)
            self.assertEqual(hook.apply_form("QP-A", lambda: d), d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
