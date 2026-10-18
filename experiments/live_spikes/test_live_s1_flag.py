"""
Offline tests for P8 step S1: the per-question `live` choice (AgentState["live"]) reaches every place that used to read LIVE_FETCH alone
(docs/phase_j_live_fetch_plan.md, P8.3 S1). No network, no LLM.   Run from the repo root:
    LANGFUSE_TRACING_ENABLED=false python -W ignore -m unittest experiments.live_spikes.test_live_s1_flag -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx
from langchain_core.messages import HumanMessage, ToolMessage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rag.live import config, hook, prefetch  # noqa: E402
from rag.live.fetcher import Fetcher  # noqa: E402
from rag.live.ratelimit import RateLimiter  # noqa: E402

URL = "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學"
SNAP = {"url": URL, "title": "休學", "subdomain": "aca", "text": "reg QP-T01-03-02 ext 62160"}
PAGE_HTML = b"<html><body><div class='item-page'><p>reg QP-T01-03-02 ext 62160</p></div></body></html>"


def env(**kw):
    """Replace LIVE_FETCH for one test: a value sets it, None removes it."""
    base = {k: v for k, v in os.environ.items() if k != "LIVE_FETCH"}
    if kw.get("LIVE_FETCH") is not None:
        base["LIVE_FETCH"] = kw["LIVE_FETCH"]
    return mock.patch.dict(os.environ, base, clear=True)


class TestLiveEnabled(unittest.TestCase):
    def test_truth_table(self):
        # (LIVE_FETCH, request) -> enabled.  None = unset / not said.
        table = {
            (None, None): False,        # the CLI default, exactly as before P8
            (None, True): True,         # server: the front end's switch decides
            (None, False): False,
            ("", None): False,
            ("", True): True,
            ("on", None): True,         # as before
            ("on", True): True,
            ("on", False): False,       # the switch can still turn it off for one question
            ("off", None): False,
            ("off", True): False,       # kill switch beats the request
            ("off", False): False,
            ("garbage", True): False,   # anything unrecognised behaves as off, like live_mode()
            ("ON ", True): True,        # case and spaces are ignored
        }
        for (var, req), want in table.items():
            with env(LIVE_FETCH=var):
                self.assertEqual(config.live_enabled(req), want, (var, req))

    def test_live_mode_is_unchanged(self):
        with env(LIVE_FETCH="on"):
            self.assertEqual(config.live_mode(), "on")
        with env(LIVE_FETCH=None):
            self.assertEqual(config.live_mode(), "off")


class Counting(unittest.TestCase):
    def setUp(self):
        self.hits = []
        hook._fetcher = Fetcher(limiter=RateLimiter(sleep=lambda s: None), transport=httpx.MockTransport(self._handle),
                                sleep=lambda s: None)

    def tearDown(self):
        hook._fetcher = None

    def _handle(self, request):
        self.hits.append(str(request.url))
        return httpx.Response(200, content=PAGE_HTML)


class TestHook(Counting):
    def test_apply_page_honours_the_question_choice(self):
        with env(LIVE_FETCH="on"):
            out = hook.apply_page(URL, SNAP, live=False)
        self.assertEqual(self.hits, [])
        self.assertEqual({k: v for k, v in out.items() if k not in ("live_marker", "live_state")}, SNAP)   # same page; S4 adds a "snapshot" marker
        self.assertEqual(out["live_state"], "snapshot")
        with env(LIVE_FETCH=None):                       # server without the variable: the request alone turns it on
            out = hook.apply_page(URL, dict(SNAP), live=True)
        self.assertEqual(len(self.hits), 1)
        self.assertEqual(out["live_state"], "live_same")
        with env(LIVE_FETCH="off"):
            self.hits.clear()
            self.assertIs(hook.apply_page(URL, SNAP, live=True), SNAP)
        self.assertEqual(self.hits, [])

    def test_apply_page_without_a_choice_follows_the_variable_as_before(self):
        with env(LIVE_FETCH=None):
            self.assertIs(hook.apply_page(URL, SNAP), SNAP)
        self.assertEqual(self.hits, [])
        with env(LIVE_FETCH="on"):
            self.assertIn("live_marker", hook.apply_page(URL, dict(SNAP)))

    def test_apply_form_honours_the_question_choice(self):
        snap = {"form_id": "QP-A", "form_title": "t", "text": "x"}
        fake = mock.Mock(return_value=SimpleNamespace(ok=False, error="network", detail="", discontinued=False, title="", unit="", text="",
                                                      elapsed=0.0, requests=1, fetched_at=0.0, from_cache=False))
        with mock.patch("rag.live.forms.fetch_form", fake):
            with env(LIVE_FETCH="on"):
                out = hook.apply_form("QP-A", dict(snap), live=False)
            self.assertEqual({k: v for k, v in out.items() if k not in ("live_marker", "live_state")}, snap)
            self.assertEqual(out["live_state"], "snapshot")
            fake.assert_not_called()
            with env(LIVE_FETCH=None):
                hook.apply_form("QP-A", dict(snap), live=True)
            fake.assert_called_once()


class TestPrefetchGate(unittest.TestCase):
    def _start(self, live, var, prefetch_on=True):
        store, deps = mock.Mock(), mock.Mock()
        deps.extract_form_ids.return_value = ["QP-A"]
        store.claim_page.return_value = True
        envs = {"LIVE_PREFETCH": "on" if prefetch_on else "off"}
        with env(LIVE_FETCH=var), mock.patch.dict(os.environ, envs):
            return prefetch.maybe_start(URL, dict(SNAP), store=store, deps=deps, live=live), store

    def test_gate(self):
        self.assertFalse(self._start(False, "on")[0])        # the question turned live off
        self.assertTrue(self._start(True, None)[0])          # no variable: the request turns live (and so the prefetch) on
        self.assertFalse(self._start(True, "off")[0])        # kill switch
        self.assertFalse(self._start(True, None, prefetch_on=False)[0])   # prefetch itself stays opt-in
        self.assertTrue(self._start(None, "on")[0])          # as before

    def test_the_chain_forces_live_on_its_form_fetch(self):
        # a live question without LIVE_FETCH in the environment: the chain's apply_form call must not fall back to "off"
        with mock.patch("rag.live.hook.apply_form") as af, env(LIVE_FETCH=None):
            prefetch.Deps().live_form("QP-A", lambda: {})
        self.assertEqual(af.call_args.kwargs.get("live"), True)


class TestTools(Counting):
    def test_get_page_tool(self):
        from rag.agentic.tools import page as pg
        with mock.patch.object(pg, "_get_page_raw", lambda url, subdomain=None: dict(SNAP)):
            with env(LIVE_FETCH="on"):
                pg.get_page_tool.func(URL, {"live": False})
            self.assertEqual(self.hits, [])
            with env(LIVE_FETCH=None):
                out = pg.get_page_tool.func(URL, {"live": True})
            self.assertEqual(len(self.hits), 1)
            self.assertIn("[live:src", out)

    def test_extract_links_tool(self):
        from rag.agentic.tools import page as pg
        with mock.patch.object(pg, "_get_page_raw", lambda url, subdomain=None: dict(SNAP)):
            with env(LIVE_FETCH="on"):
                pg.extract_links_tool.func(URL, {"live": False})
            self.assertEqual(self.hits, [])
            with env(LIVE_FETCH=None):
                pg.extract_links_tool.func(URL, {"live": True})
            self.assertEqual(len(self.hits), 1)

    def test_get_form_tool_and_the_plain_function(self):
        from rag.agentic.tools import form as ft
        fake = mock.Mock(return_value=SimpleNamespace(ok=False, error="network", detail="", discontinued=False, title="", unit="", text="",
                                                      elapsed=0.0, requests=1, fetched_at=0.0, from_cache=False))
        snap = {"form_id": "QP-A", "form_title": "t", "text": "x"}
        with mock.patch("rag.live.forms.fetch_form", fake), mock.patch.object(ft, "_get_form_raw", lambda fid: dict(snap)), \
                mock.patch.object(ft, "get_store", lambda: prefetch.PrefetchStore()):
            with env(LIVE_FETCH="on"):
                ft.get_form_tool.func("QP-A", {"live": False})
                ft.fetch_form_for_agent("QP-A", False)
            fake.assert_not_called()
            with env(LIVE_FETCH="off"):
                ft.get_form_tool.func("QP-A", {"live": True})
            fake.assert_not_called()
            with env(LIVE_FETCH=None):
                ft.get_form_tool.func("QP-A", {"live": True})
            self.assertEqual(fake.call_count, 1)

    def test_get_form_tool_text_is_unchanged_without_live(self):
        from rag.agentic.tools import form as ft
        snap = {"form_id": "QP-A", "form_title": "申請書", "text": "內文"}
        with mock.patch.object(ft, "_get_form_raw", lambda fid: dict(snap)), mock.patch.object(ft, "get_store", lambda: prefetch.PrefetchStore()), \
                env(LIVE_FETCH=None):
            self.assertEqual(ft.get_form_tool.func("QP-A", {}), "get_form 取得表單 申請書\n\n內文")
            self.assertEqual(ft.fetch_form_for_agent("QP-A"), "get_form 取得表單 申請書\n\n內文")


class TestNodes(unittest.TestCase):
    def test_contact_node(self):
        import rag.agentic.nodes.contact as cn
        skill = mock.Mock()
        skill.run.return_value = {"註冊組": {"contacts_source": "index"}}
        skill.format_context.return_value = "[contacts body]"
        live_result = SimpleNamespace(pages={}, uncovered=["註冊組"])      # one office with no live check: the ledger section then has a line
        fetch = mock.Mock(return_value=live_result)
        state = {"query": "q", "messages": [HumanMessage(content="x")]}
        patches = [mock.patch.object(cn, "_detect_offices", return_value=["註冊組"]),
                   mock.patch("rag.skills.office_lookup_skill.OfficeLookupSkill", return_value=skill),
                   mock.patch("rag.live.contacts.fetch_contact_pages", fetch),
                   mock.patch("rag.live.contacts.default_backends", return_value=(None, None))]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with env(LIVE_FETCH="on"):
            out = cn.contact_node(dict(state, live=False))["messages"][0].content
        fetch.assert_not_called()
        self.assertNotIn("[live:src", out)
        self.assertNotIn("[contacts:", out)

        with env(LIVE_FETCH=None):
            out = cn.contact_node(dict(state, live=True))["messages"][0].content
        fetch.assert_called_once()
        self.assertIn("[contacts:", out)                       # the ledger section is there

        fetch.reset_mock()
        with env(LIVE_FETCH="off"):
            cn.contact_node(dict(state, live=True))
        fetch.assert_not_called()

        with env(LIVE_FETCH=None):                             # no choice, no variable: exactly the pre-P8 behaviour
            out = cn.contact_node(state)["messages"][0].content
        fetch.assert_not_called()
        self.assertNotIn("[contacts:", out)

    def test_resource_node_passes_the_choice_to_every_form_fetch(self):
        from rag.agentic.nodes import resource
        seen = mock.Mock(side_effect=lambda fid, live=None: f"get_form 取得表單 {fid}\n\nbody")
        msgs = [ToolMessage(content="[偵測到表單編號: QP-T01-03-02, QP-T01-03-04]", tool_call_id="1")]
        for live in (False, True, None):
            seen.reset_mock()
            state = {"query": "q", "subdomain_hint": "aca", "messages": msgs}
            if live is not None:
                state["live"] = live
            with mock.patch.object(resource, "fetch_form_for_agent", seen), mock.patch.object(resource, "_detect_offices", return_value=[]):
                resource.resource_node(state)
            self.assertTrue(seen.call_args_list)
            self.assertEqual({c.args[1] for c in seen.call_args_list}, {live}, live)


class TestStateAndEntryPoints(unittest.TestCase):
    def test_initial_state_carries_the_choice(self):
        import agentic_rag
        self.assertIsNone(agentic_rag.initial_state("q")["live"])
        self.assertIs(agentic_rag.initial_state("q", None, True)["live"], True)
        self.assertIs(agentic_rag.initial_state("q", None, False)["live"], False)

    def test_cli_flag_is_wired_to_run(self):
        src = (ROOT / "agentic_rag.py").read_text(encoding="utf-8")
        self.assertIn('"--live"', src)
        self.assertIn("live=None if args.live is None", src)


if __name__ == "__main__":
    unittest.main()
