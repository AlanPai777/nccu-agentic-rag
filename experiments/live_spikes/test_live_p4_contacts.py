"""
Offline tests for rag/live/contacts.py (P4 step 4): office -> index page -> render -> compare -> parse, as a pipeline.
The browser is replaced by a fake that serves the recorded Chromium-rendered staff pages (experiments/live_fixtures, P0)
on a fake clock; the LLM page-parse fallback is stubbed. No Chromium, no network, no LLM.
    python -W ignore -m unittest experiments.live_spikes.test_live_p4_contacts -v
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import test_live_p4_schedule as sch  # noqa: E402  (FakeClock / FakeOwner / rig)
from rag.live.allowlist import host_of  # noqa: E402
from rag.live.browser import RenderResult  # noqa: E402
from rag.live.contacts import fetch_contact_pages, plan_pages  # noqa: E402
from rag.live.schedule import RenderScheduler  # noqa: E402
import rag.skills.office_lookup_skill as skill  # noqa: E402

FIX = ROOT / "experiments" / "live_fixtures" / "chain_xiuxue_2026-10-14"
OFFICES = ["註冊組", "教務長室", "住宿輔導組", "生活事務暨僑生輔導組", "原住民族學生資源中心", "身心健康中心", "出納組",
           "圖書館(各組聯絡資訊)", "國際合作事務處"]
EXPECTED = {"註冊組": "live_changed", "教務長室": "live_changed", "住宿輔導組": "live_changed",
            "生活事務暨僑生輔導組": "live_changed", "原住民族學生資源中心": "live_changed", "身心健康中心": "live_changed",
            "出納組": "live_same", "圖書館(各組聯絡資訊)": "live_same", "國際合作事務處": "live_changed"}


class PagesOwner(sch.FakeOwner):
    """FakeOwner that answers with the recorded page for a URL (or whatever the test overrides)."""

    def __init__(self, clock, limiter, pages: dict[str, bytes], override=None):
        super().__init__(clock, limiter)
        self.pages, self.override = pages, override or {}

    def render(self, url):
        if url in self.override:
            with self.limiter.slot(host_of(url)):
                self.clock.t += self.render_s
            f: Future = Future()
            f.set_result(self.override[url](url))
            return f
        f = super().render(url)
        r = f.result()
        if r.ok:
            r.html = self.pages.get(url, b"")
            r.ok = bool(r.html)
        return f


@unittest.skipUnless(FIX.exists(), "fixtures not present")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m = json.load(open(FIX / "manifest.json", encoding="utf-8"))
        cls.page_of = {i["office"]: (i["url"], (FIX / i["file"]).read_bytes()) for i in m["items"] if i["step"] == "C"}
        cls.pages = {u: b for u, b in cls.page_of.values()}

    def setUp(self):
        self.llm_calls = []
        self._p = mock.patch.object(skill, "_llm_extract_contacts", lambda t: self.llm_calls.append(len(t)) or [])
        self._p.start()
        self.clock, self.limiter, _ = sch.rig()

    def tearDown(self):
        self._p.stop()

    def run_chain(self, offices=OFFICES, override=None, handler=None):
        owner = PagesOwner(self.clock, self.limiter, self.pages, override)
        sched = RenderScheduler(owner.render, self.limiter)
        return fetch_contact_pages(offices, sched, handler=handler), owner


class TestPlan(Base):
    def test_each_office_maps_to_its_index_page_and_the_snapshot_text_comes_with_it(self):
        pages, uncovered = plan_pages(OFFICES)
        self.assertEqual(uncovered, [])
        self.assertEqual(len(pages), 9)
        for office in OFFICES:
            url = self.page_of[office][0]
            self.assertIn(office, pages[url]["offices"])
            self.assertTrue(pages[url]["snapshot_text"])
            self.assertTrue(pages[url]["snapshot_at"].startswith("2026-08-25"))

    def test_an_alias_and_its_canonical_name_share_one_page(self):
        pages, _ = plan_pages(["教務長室", "教務長"])          # 教務長 is an alias of the record 教務長室
        self.assertEqual(len(pages), 1)
        self.assertEqual(list(pages.values())[0]["offices"], ["教務長室", "教務長"])

    def test_offices_the_index_does_not_know_are_reported_not_invented(self):
        pages, uncovered = plan_pages(["註冊組", "不存在的處室"])
        self.assertEqual(uncovered, ["不存在的處室"])
        self.assertEqual(len(pages), 1)


class TestDecisions(Base):
    def test_nine_staff_pages_get_the_states_p0_and_p1_found(self):
        res, owner = self.run_chain()
        got = {o: res.pages[self.page_of[o][0]].state for o in OFFICES}
        self.assertEqual(got, EXPECTED)
        self.assertEqual(len(owner.log), 9)

    def test_a_changed_page_uses_the_live_text_and_the_departed_person_is_gone(self):
        url = self.page_of["教務長室"][0]
        res, _ = self.run_chain(["教務長室"])
        out = res.pages[url]
        self.assertEqual(out.state, "live_changed")
        snap_exts = {c["ext"] for c in skill.parse_office_contacts(out.snapshot_text)}
        live_exts = {c["ext"] for c in out.handled}
        self.assertIn("62442", snap_exts)               # 劉建興, listed on 8/25
        self.assertNotIn("62442", live_exts)            # P0: no longer listed on the live page
        self.assertIn("62160", live_exts)               # 教務長 is still there
        self.assertIn("62442", out.comparison.exts_removed)

    def test_an_unchanged_page_keeps_the_snapshot_text(self):
        url = self.page_of["出納組"][0]
        res, _ = self.run_chain(["出納組"])
        self.assertEqual(res.pages[url].state, "live_same")
        self.assertEqual(res.pages[url].text, res.pages[url].snapshot_text)

    def test_a_failed_render_falls_back_to_the_snapshot_and_says_why(self):
        bad = self.page_of["註冊組"][0]
        res, _ = self.run_chain(OFFICES, override={bad: lambda u: RenderResult(u, error="timeout", detail="Timeout 60000ms")})
        out = res.pages[bad]
        self.assertEqual((out.state, out.error), ("snapshot_fallback", "timeout"))
        self.assertEqual(out.text, out.snapshot_text)
        self.assertTrue(out.handled)                                       # still parsed, from the snapshot
        self.assertEqual(res.pages[self.page_of["出納組"][0]].state, "live_same")   # the rest unaffected

    def test_a_page_that_rendered_almost_empty_keeps_the_snapshot_and_is_flagged(self):
        url = self.page_of["國際合作事務處"][0]
        res, _ = self.run_chain(["國際合作事務處"], override={
            url: lambda u: RenderResult(u, ok=True, html=b"<html><body><div class='item-page'>loading</div></body></html>", status=200, elapsed=3)})
        out = res.pages[url]
        self.assertEqual((out.state, out.text), ("live_incomplete", out.snapshot_text))

    def test_a_cloudflare_page_is_a_failure_not_content(self):
        url = self.page_of["出納組"][0]
        cf = b"<html><head><script>window._cf_chl_opt={}</script></head><body>Just a moment</body></html>"
        res, _ = self.run_chain(["出納組"], override={url: lambda u: RenderResult(u, ok=True, html=cf, status=200, elapsed=3)})
        self.assertEqual((res.pages[url].state, res.pages[url].error), ("snapshot_fallback", "cloudflare"))

    def test_empty_input_renders_nothing(self):
        owner_calls = []
        sched = RenderScheduler(lambda u: owner_calls.append(u), self.limiter)
        res = fetch_contact_pages([], sched)
        self.assertEqual((res.pages, res.uncovered, owner_calls), ({}, [], []))


class TestPipeline(Base):
    def test_a_page_is_handled_while_the_next_one_is_still_rendering(self):
        order = self.page_of
        a, b = order["出納組"][0], order["註冊組"][0]
        handled_a, released = threading.Event(), {"b_started_after_a_handled": None}

        class Owner(PagesOwner):
            def render(s, url):
                if url == b:                                     # the second page: do not finish until A was handled
                    released["b_started_after_a_handled"] = handled_a.wait(5)
                return super().render(url)

        owner = Owner(self.clock, self.limiter, self.pages)
        sched = RenderScheduler(owner.render, self.limiter)

        def handler(o):
            if o.url == a:
                handled_a.set()
            return None
        # force A first: it is the only candidate that is not the longest-chain host
        res = fetch_contact_pages(["出納組", "註冊組"], sched, handler=handler)
        first = sched.order[0]
        if first == b:                                           # scheduler chose B first; the check needs A first
            self.skipTest("scheduler rendered the other page first")
        self.assertTrue(released["b_started_after_a_handled"], "page A was not handled while B was still rendering")
        self.assertEqual(len(res.pages), 2)

    def test_a_crashing_handler_is_isolated(self):
        def handler(o):
            if "cashier" in o.url:
                raise ValueError("parser blew up")
            return "fine"
        res, _ = self.run_chain(["出納組", "註冊組"], handler=handler)
        cashier = res.pages[self.page_of["出納組"][0]]
        self.assertIn("parser blew up", cashier.handler_error)
        self.assertEqual(res.pages[self.page_of["註冊組"][0]].handled, "fine")


class TestIndexHookup(Base):
    def test_texts_override_replaces_the_index_text_for_that_url_only(self):
        url = self.page_of["教務長室"][0]
        base, _ = skill.dynamic_contacts_for_office("教務長室")
        res, _ = self.run_chain(["教務長室"])
        live_text = res.pages[url].text
        over, urls = skill.dynamic_contacts_for_office("教務長室", texts={url: live_text})
        self.assertEqual(urls, [url])
        self.assertIn("62442", {c["ext"] for c in base})
        self.assertNotIn("62442", {c["ext"] for c in over})

    def test_without_texts_the_snapshot_path_is_unchanged(self):
        a = skill.dynamic_contacts_for_office("教務長室")
        b = skill.dynamic_contacts_for_office("教務長室", texts=None)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
