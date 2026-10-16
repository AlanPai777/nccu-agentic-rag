"""
Offline tests for rag/live/contacts.py (P4 "httpx 優先", H2+H3): office -> index page -> httpx -> compare -> parse, escalating to
Chromium only when the static result is not enough. The 'network' is the recorded staff pages served through a real Fetcher over
httpx.MockTransport; the browser is a fake. The LLM page-parse fallback is stubbed. No Chromium, no network, no LLM.
    python -W ignore -m unittest experiments.live_spikes.test_live_p4_contacts -v
"""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import p4_fakes as fk  # noqa: E402
import rag.skills.office_lookup_skill as skill  # noqa: E402
from rag.live import config  # noqa: E402
from rag.live.browser import RenderResult  # noqa: E402
from rag.live.contacts import fetch_contact_pages, plan_pages  # noqa: E402
from rag.live.ratelimit import RateLimiter  # noqa: E402

FIX = ROOT / "experiments" / "live_fixtures" / "chain_xiuxue_2026-10-14"
OFFICES = ["註冊組", "教務長室", "住宿輔導組", "生活事務暨僑生輔導組", "原住民族學生資源中心", "身心健康中心", "出納組",
           "圖書館(各組聯絡資訊)", "國際合作事務處"]
EXPECTED = {"註冊組": "live_changed", "教務長室": "live_changed", "住宿輔導組": "live_changed",
            "生活事務暨僑生輔導組": "live_changed", "原住民族學生資源中心": "live_changed", "身心健康中心": "live_changed",
            "出納組": "live_same", "圖書館(各組聯絡資訊)": "live_same", "國際合作事務處": "live_changed"}
OIC = "國際合作事務處"


@unittest.skipUnless(FIX.exists(), "fixtures not present")
class Base(unittest.TestCase):
    """`pages` = the recorded pages. P1 showed the Chromium-rendered pages and the static ones were identical for eight of the
    nine, so the recordings stand in for the static responses; oic's static page is a JavaScript shell (JS_SHELL)."""

    @classmethod
    def setUpClass(cls):
        m = json.load(open(FIX / "manifest.json", encoding="utf-8"))
        cls.page_of = {i["office"]: (i["url"], (FIX / i["file"]).read_bytes()) for i in m["items"] if i["step"] == "C"}
        cls.pages = {u: b for u, b in cls.page_of.values()}

    def setUp(self):
        self.llm_calls: list[int] = []
        self._p = mock.patch.object(skill, "_llm_extract_contacts", lambda t: self.llm_calls.append(len(t)) or [])
        self._p.start()
        self.net_log: list[str] = []

    def tearDown(self):
        self._p.stop()

    def url(self, office):
        return self.page_of[office][0]

    def static_pages(self, **replace):
        """The static view of the site: the recordings, with oic as a JS shell, plus any {office: bytes} replacements."""
        pages = dict(self.pages)
        pages[self.url(OIC)] = fk.JS_SHELL
        for office, body in replace.items():
            pages[self.url(office)] = body
        return pages

    def run_chain(self, offices=OFFICES, static=None, static_over=None, render_over=None, handler=None, limiter=None):
        fetcher = fk.static_fetcher(static if static is not None else self.static_pages(), static_over, limiter, self.net_log)
        render = fk.FakeRender(self.pages, render_over)
        res = fetch_contact_pages(offices, lambda u: fetcher.fetch(u, kind="contact", use_cache=False), render, handler=handler)
        return res, render


class TestPlan(Base):
    def test_each_office_maps_to_its_index_page_and_the_snapshot_text_comes_with_it(self):
        pages, uncovered = plan_pages(OFFICES)
        self.assertEqual(uncovered, [])
        self.assertEqual(len(pages), 9)
        for office in OFFICES:
            info = pages[self.url(office)]
            self.assertIn(office, info["offices"])
            self.assertTrue(info["snapshot_text"])
            self.assertTrue(info["snapshot_at"].startswith("2026-08-25"))

    def test_an_alias_and_its_canonical_name_share_one_page(self):
        pages, _ = plan_pages(["教務長室", "教務長"])
        self.assertEqual(len(pages), 1)
        self.assertEqual(list(pages.values())[0]["offices"], ["教務長室", "教務長"])

    def test_offices_the_index_does_not_know_are_reported_not_invented(self):
        pages, uncovered = plan_pages(["註冊組", "不存在的處室"])
        self.assertEqual(uncovered, ["不存在的處室"])
        self.assertEqual(len(pages), 1)


class TestStaticFirst(Base):
    def test_the_eight_server_rendered_pages_never_reach_chromium_and_oic_does(self):
        res, render = self.run_chain()
        self.assertEqual(render.calls, [self.url(OIC)])                       # exactly one page escalated
        for office in OFFICES:
            o = res.pages[self.url(office)]
            self.assertEqual(o.method, "chromium" if office == OIC else "httpx", office)

    def test_states_match_what_p0_and_p1_found(self):
        res, _ = self.run_chain()
        self.assertEqual({o: res.pages[self.url(o)].state for o in OFFICES}, EXPECTED)

    def test_request_count_is_one_per_page_plus_oics_browser_visit(self):
        res, render = self.run_chain()
        static = sum(o.requests for o in res.pages.values() if o.method == "httpx")
        self.assertEqual(static, 8)                                           # eight pages, one GET each
        self.assertEqual(len(self.net_log), 9)                                # + oic's static try
        oic = res.pages[self.url(OIC)]
        self.assertEqual((oic.static_requests, oic.requests), (1, 40))        # what the escalation cost, visible

    def test_oic_is_escalated_because_the_static_page_is_nearly_empty(self):
        res, _ = self.run_chain()
        oic = res.pages[self.url(OIC)]
        self.assertTrue(oic.escalated.startswith("B:similarity="), oic.escalated)
        self.assertIn("陳美芬 國合長", oic.text)                                # the Chromium text, with the names

    def test_a_changed_page_uses_the_live_text_and_the_departed_person_is_gone(self):
        res, _ = self.run_chain(["教務長室"])
        out = res.pages[self.url("教務長室")]
        self.assertEqual(out.state, "live_changed")
        self.assertIn("62442", {c["ext"] for c in skill.parse_office_contacts(out.snapshot_text)})
        live_exts = {c["ext"] for c in out.handled}
        self.assertNotIn("62442", live_exts)
        self.assertIn("62160", live_exts)

    def test_an_unchanged_page_keeps_the_snapshot_text(self):
        res, _ = self.run_chain(["出納組"])
        out = res.pages[self.url("出納組")]
        self.assertEqual((out.state, out.text), ("live_same", out.snapshot_text))

    def test_cashier_is_fetched_without_tls_verification_and_says_so(self):
        res, _ = self.run_chain(["出納組", "註冊組"])
        self.assertTrue(res.pages[self.url("出納組")].tls_unverified)
        self.assertFalse(res.pages[self.url("註冊組")].tls_unverified)

    def test_the_library_page_counts_as_static_ok_despite_its_noscript_text_and_empty_counter(self):
        lib = self.page_of["圖書館(各組聯絡資訊)"][1].decode("utf-8")
        static = lib.replace("<body", "<body><noscript>您的瀏覽器不支援JavaScript功能，若網頁功能無法正常使用時，請開啟瀏覽器JavaScript狀態</noscript>", 1) \
            if "<body" in lib else lib
        res, render = self.run_chain(["圖書館(各組聯絡資訊)"], static=self.static_pages(**{"圖書館(各組聯絡資訊)": static.encode()}))
        self.assertEqual(render.calls, [])
        self.assertEqual(res.pages[self.url("圖書館(各組聯絡資訊)")].state, "live_same")


class TestEscalationPolicy(Base):
    def test_timeouts_and_server_errors_fall_back_to_the_snapshot_and_do_not_summon_a_browser(self):
        url = self.url("註冊組")
        for name, over in (("timeout", httpx.ReadTimeout("slow")), ("503", lambda r: httpx.Response(503)),
                           ("429", lambda r: httpx.Response(429))):
            with self.subTest(name):
                res, render = self.run_chain(["註冊組"], static_over={url: over})
                o = res.pages[url]
                self.assertEqual(o.state, "snapshot_fallback")
                self.assertEqual(o.text, o.snapshot_text)
                self.assertTrue(o.handled)                                    # still parsed, from the snapshot
                self.assertEqual(render.calls, [])

    def test_403_escalates(self):
        url = self.url("註冊組")
        res, render = self.run_chain(["註冊組"], static_over={url: lambda r: httpx.Response(403)})
        self.assertEqual(len(render.calls), 1)
        o = res.pages[url]
        self.assertEqual((o.method, o.escalated), ("chromium", "A:http_403"))

    def test_an_empty_page_and_a_cloudflare_page_escalate(self):
        cf = b"<html><head><script>window._cf_chl_opt={}</script></head><body>Just a moment</body></html>"
        for name, body, reason in (("empty", b"<html><body></body></html>", "A:empty"), ("cloudflare", cf, "A:cloudflare")):
            with self.subTest(name):
                res, render = self.run_chain(["註冊組"], static=self.static_pages(註冊組=body))
                o = res.pages[self.url("註冊組")]
                self.assertEqual((o.method, o.escalated, len(render.calls)), ("chromium", reason, 1))

    def test_a_page_with_no_contacts_escalates_even_when_it_matches_the_snapshot(self):
        """Condition C: the snapshot of the 'office' 教務處 is the aca home page, which lists nobody. The static copy equals the
        snapshot (no B), the parse finds nobody (C) -> Chromium is asked, whatever the snapshot looked like."""
        pages, _ = plan_pages(["教務處"])
        url, info = next(iter(pages.items()))
        body = ("<html><body><div class='item-page'>" + "".join(f"<p>{l}</p>" for l in info["snapshot_text"].split("\n") if l.strip())
                + "</div></body></html>").encode()
        fetcher = fk.static_fetcher({url: body})
        render = fk.FakeRender({url: body})
        res = fetch_contact_pages(["教務處"], lambda u: fetcher.fetch(u, kind="contact", use_cache=False), render)
        o = res.pages[url]
        self.assertEqual(o.escalated, "C:no_contacts")
        self.assertEqual(len(render.calls), 1)

    def test_condition_b_alone_escalates_when_the_parser_would_still_find_someone(self):
        """A static page that is nothing like the snapshot but still 'has people' (the handler is forced to say so) is caught by B."""
        res, render = self.run_chain(["註冊組"], static=self.static_pages(註冊組=fk.JS_SHELL),
                                     handler=lambda o: [{"name": "x", "ext": "11111", "email": None, "duty": ""}])
        o = res.pages[self.url("註冊組")]
        self.assertTrue(o.escalated.startswith("B:"), o.escalated)
        self.assertEqual((len(render.calls), o.method), (1, "chromium"))

    def test_condition_a_alone_escalates_an_empty_page_even_if_the_parser_would_find_someone(self):
        res, render = self.run_chain(["註冊組"], static=self.static_pages(註冊組=b"<html><body></body></html>"),
                                     handler=lambda o: [{"name": "x", "ext": "11111", "email": None, "duty": ""}])
        self.assertEqual(res.pages[self.url("註冊組")].escalated, "A:empty")

    def test_escalating_on_a_or_b_skips_the_static_parse_c_pays_for_both(self):
        parsed: list[str] = []
        handler = lambda o: parsed.append(o.method) or skill.parse_office_contacts(o.text)
        self.run_chain([OIC], handler=handler)                                 # B: static never parsed, Chromium parsed once
        self.assertEqual(parsed, ["chromium"])

    def test_if_chromium_also_fails_the_snapshot_stands_and_says_so(self):
        url = self.url(OIC)
        res, render = self.run_chain([OIC], render_over={url: lambda u: RenderResult(u, error="timeout", detail="Timeout")})
        o = res.pages[url]
        self.assertEqual((o.state, o.method, o.text), ("snapshot_fallback", "chromium", o.snapshot_text))
        self.assertEqual(o.escalated.split(":")[0], "B")

    def test_a_chromium_future_that_raises_is_contained(self):
        url = self.url(OIC)
        fetcher = fk.static_fetcher(self.static_pages())

        def boom(u):
            raise RuntimeError("owner is gone")
        res = fetch_contact_pages([OIC], lambda u: fetcher.fetch(u, kind="contact", use_cache=False), boom)
        self.assertEqual(res.pages[url].state, "snapshot_fallback")

    def test_the_static_fetcher_raising_is_contained(self):
        def boom(u):
            raise RuntimeError("network stack exploded")
        res = fetch_contact_pages(["註冊組"], boom, fk.FakeRender({}))
        self.assertEqual(res.pages[self.url("註冊組")].state, "snapshot_fallback")


class TestConcurrency(Base):
    def test_pages_are_fetched_side_by_side_not_one_after_another(self):
        barrier = threading.Barrier(3, timeout=5)                              # three pages must be in flight together
        met: list[int] = []
        urls = [self.url(o) for o in ("註冊組", "出納組", "圖書館(各組聯絡資訊)")]

        def meet(req):
            barrier.wait()
            met.append(1)                                                      # only reached if all three really overlapped
            return fk.page_response(self.pages[self._match(req)])
        res, _ = self.run_chain(["註冊組", "出納組", "圖書館(各組聯絡資訊)"], static_over={u: meet for u in urls})
        self.assertEqual(len(met), 3)
        self.assertEqual({o.method for o in res.pages.values()}, {"httpx"})

    def _match(self, req):
        from urllib.parse import unquote
        target = unquote(str(req.url))
        return next(u for u in self.pages if unquote(u) == target)

    def test_osa_waits_its_turns_without_holding_up_other_hosts(self):
        osa = [o for o in OFFICES if "osa.nccu" in self.url(o)]
        others = ["註冊組", "出納組", "圖書館(各組聯絡資訊)", OIC]            # one page per host: no gap of their own to wait for
        gap = 0.4
        with mock.patch.dict(config.HOST_POLICY, {"osa.nccu.edu.tw": config.HostPolicy(gap, 1)}):
            res, _ = self.run_chain(osa + others, limiter=RateLimiter())       # real clock, real (short) osa gap
        self.assertEqual(len(res.pages), len(osa) + len(others))
        t0 = min(t for t, _ in self.net_log)
        osa_t = sorted(t - t0 for t, u in self.net_log if "osa.nccu" in u)
        other_t = [t - t0 for t, u in self.net_log if "osa.nccu" not in u]
        self.assertEqual(len(osa_t), 4)
        for earlier, later in zip(osa_t, osa_t[1:]):
            self.assertGreaterEqual(later - earlier, gap - 0.05)               # osa's requests are spaced by its gap
        self.assertLess(max(other_t), gap)                                     # every other host was served inside osa's FIRST gap


class TestPipeline(Base):
    def test_a_page_is_handled_while_another_is_still_being_fetched(self):
        a, b = self.url("出納組"), self.url("註冊組")
        handled_a, seen = threading.Event(), {}

        def slow_b(req):
            seen["b_waited_for_a"] = handled_a.wait(5)
            return fk.page_response(self.pages[b])
        handler = lambda o: handled_a.set() if o.url == a else None
        res, _ = self.run_chain(["出納組", "註冊組"], static_over={b: slow_b}, handler=handler)
        self.assertTrue(seen["b_waited_for_a"], "page A was not handled while B was still in flight")
        self.assertEqual(len(res.pages), 2)

    def test_a_crashing_handler_is_isolated(self):
        def handler(o):
            if "cashier" in o.url:
                raise ValueError("parser blew up")
            return "fine"
        res, _ = self.run_chain(["出納組", "註冊組"], handler=handler)
        self.assertIn("parser blew up", res.pages[self.url("出納組")].handler_error)
        self.assertEqual(res.pages[self.url("註冊組")].handled, "fine")

    def test_empty_input_does_nothing(self):
        calls = []
        res = fetch_contact_pages([], lambda u: calls.append(u), lambda u: calls.append(u))
        self.assertEqual((res.pages, res.uncovered, calls), ({}, [], []))


class TestIndexHookup(Base):
    def test_texts_override_replaces_the_index_text_for_that_url_only(self):
        url = self.url("教務長室")
        base, _ = skill.dynamic_contacts_for_office("教務長室")
        res, _ = self.run_chain(["教務長室"])
        over, urls = skill.dynamic_contacts_for_office("教務長室", texts={url: res.pages[url].text})
        self.assertEqual(urls, [url])
        self.assertIn("62442", {c["ext"] for c in base})
        self.assertNotIn("62442", {c["ext"] for c in over})

    def test_without_texts_the_snapshot_path_is_unchanged(self):
        self.assertEqual(skill.dynamic_contacts_for_office("教務長室", texts=None), skill.dynamic_contacts_for_office("教務長室"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
