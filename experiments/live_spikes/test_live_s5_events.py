"""
Offline tests for P8 step S5: live progress events (rag/live/events.py), the tools and nodes that emit them, and server.py forwarding them
(docs/phase_j_live_fetch_plan.md, P8.3 S5). Everything runs INSIDE a streaming LangGraph run (astream with the custom stream), because that is
the only place worker-thread emits can fail (S5.0). No LLM, no network, no Chromium.   Run from the repo root:
    LANGFUSE_TRACING_ENABLED=false python -W ignore -m unittest experiments.live_spikes.test_live_s5_events -v
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict
from unittest import mock

import httpx
from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from rag.live import events, hook, ledger  # noqa: E402
from rag.live.fetcher import Fetcher  # noqa: E402
from rag.live.ratelimit import RateLimiter  # noqa: E402

PAGE = "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學"
HTML = b"<html><body><div class='item-page'><p>reg ext 62160</p></div></body></html>"


class S(TypedDict):
    x: int


def run_in_graph(fn):
    """Run fn() inside one node of a streaming graph; return (custom events, fn's return value)."""
    box = {}

    def node(state):
        box["value"] = fn()
        return {}

    g = StateGraph(S)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    graph = g.compile()

    async def go():
        got = []
        async for mode, payload in graph.astream({"x": 0}, stream_mode=["updates", "custom"]):
            if mode == "custom":
                got.append(payload)
        return got

    return asyncio.run(go()), box.get("value")


def steps(evs, kind=None):
    return [e for e in evs if e.get("type") == "step" and (kind is None or e["kind"] == kind)]


class TestEvents(unittest.TestCase):
    def test_emit_without_a_listener_is_a_silent_no_op(self):
        events.emit({"type": "step"})
        with events.group("page", "t") as g:
            g.row("done", url=PAGE, title="t")

    def test_a_failing_writer_never_reaches_the_caller(self):
        def boom(event):
            raise RuntimeError("writer exploded")
        with mock.patch("langgraph.config.get_stream_writer", lambda: boom):
            events.emit({"type": "step"})

    def test_group_and_row_events_in_order_with_their_fields(self):
        def work():
            with events.group("page", "休學") as g:
                rid = g.row("start", url=PAGE, title="休學", state="pending")
                g.row("done", rid=rid, url=PAGE, title="休學", state="live_same", checked="2026-10-17T14:31", seconds=1.26)
        evs, _ = run_in_graph(work)
        kinds = [(e["kind"], e["phase"]) for e in steps(evs)]
        self.assertEqual(kinds, [("group", "start"), ("row", "start"), ("row", "done"), ("group", "done")])
        grp, start, done, end = steps(evs)
        self.assertEqual((grp["verb"], grp["title"]), ("page", "休學"))
        self.assertEqual(start["group_id"], grp["id"])
        self.assertEqual(start["id"], done["id"])                         # the done event updates the same row
        self.assertEqual((start["state"], start["label"]), ("pending", "讀取中…"))
        self.assertEqual((done["state"], done["label"], done["time"], done["seconds"]), ("live_same", "已與官網核對，內容無變動", "10/17 14:31", 1.3))
        self.assertEqual((done["host"], done["site_name"], done["url"]), ("aca.nccu.edu.tw", "教務處", PAGE))
        self.assertIsNotNone(end["seconds"])

    def test_a_row_built_from_a_marker_says_what_the_ledger_says(self):
        mk = ledger.make_marker(PAGE, "live_same", "2026-10-17T14:29", "2026-08-19", cached=True, age_min=3, title="休學")

        def work():
            with events.group("page", "休學") as g:
                g.row("done", url=PAGE, marker=mk)
        evs, _ = run_in_graph(work)
        row = steps(evs, "row")[0]
        self.assertEqual((row["state"], row["cached"], row["age_min"], row["title"]), ("live_same", True, 3, "休學"))
        self.assertEqual(row["time"], "10/17 14:29（約 3 分鐘前核對）")

    def test_database_rows_have_no_check_time(self):
        def work():
            with events.group("search", "休學") as g:
                g.row("done", url=PAGE, title="休學", state="snapshot")
        row = steps(run_in_graph(work)[0], "row")[0]
        self.assertEqual((row["state"], row["label"], row["time"], row["checked"]), ("snapshot", "使用資料庫（8/19）", "", None))

    def test_the_group_title_can_be_refined_from_its_first_row(self):
        def work(n):
            with events.group("form", "QP-A, QP-B", refine=True) as g:
                for i in range(n):
                    g.row("done", url=f"https://moltke.nccu.edu.tw/x{i}", title=f"表單{i}", state="snapshot", kind="form")
        self.assertEqual(steps(run_in_graph(lambda: work(2))[0], "group")[-1]["title"], "表單0 …")
        self.assertEqual(steps(run_in_graph(lambda: work(1))[0], "group")[-1]["title"], "表單0")
        self.assertEqual(steps(run_in_graph(lambda: work(0))[0], "group")[-1]["title"], "QP-A, QP-B")     # nothing finished: keep the title

    def test_current_group_is_set_inside_and_reset_after(self):
        self.assertIsNone(events.current_group())
        with events.group("page", "t") as g:
            self.assertIs(events.current_group(), g)
            with events.group("form", "t2") as g2:
                self.assertIs(events.current_group(), g2)
            self.assertIs(events.current_group(), g)
        self.assertIsNone(events.current_group())

    def test_workers_started_with_the_helper_deliver_rows_into_the_right_group(self):
        def work():
            with events.group("contacts", "x") as g:
                with ThreadPoolExecutor(max_workers=3) as ex:
                    futs = [events.submit_with_context(ex, lambda i=i: events.current_group().row("done", url=f"https://a{i}.nccu.edu.tw/p", title=str(i)))
                            for i in range(4)]
                    [f.result() for f in futs]
                return g.id
        evs, gid = run_in_graph(work)
        rows = steps(evs, "row")
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r["group_id"] == gid for r in rows))
        order = [(e["kind"], e["phase"]) for e in steps(evs)]
        self.assertEqual((order[0], order[-1]), (("group", "start"), ("group", "done")))     # the rows came between them

    def test_title_list(self):
        self.assertEqual(events.title_list(["註冊組", "教務長室", "出納組"]), "註冊組、教務長室、出納組")
        self.assertEqual(events.title_list(["a", "b", "c", "d"]), "a、b、c …")
        self.assertEqual(events.title_list([]), "")


class TestSearchAndGrep(unittest.TestCase):
    def test_search_texts_emits_one_database_row_and_keeps_its_text(self):
        from rag.agentic.tools import search
        ks = mock.Mock()
        ks.search.return_value = [{"subdomain": "aca", "title": "休學", "url": PAGE}]
        with mock.patch.object(search, "KeywordStore", return_value=ks), \
                mock.patch.object(search, "_judge_candidates", return_value={"good_enough": True, "selected_index": 1, "reason": "ok"}):
            evs, text = run_in_graph(lambda: search.search_texts.func({"rewritten": "休學", "query": "休學", "subdomain_hint": None}))
        self.assertEqual(text, f"search_texts('休學') 找到候選 [aca] 休學\nURL: {PAGE}\n(judge通過: ok)")
        (grp,) = steps(evs, "group")[:1]
        self.assertEqual((grp["verb"], grp["title"]), ("search", "休學"))
        (row,) = steps(evs, "row")
        self.assertEqual((row["state"], row["url"], row["label"]), ("snapshot", PAGE, "使用資料庫（8/19）"))

    def test_search_texts_with_nothing_relevant_is_a_group_without_rows(self):
        from rag.agentic.tools import search
        ks = mock.Mock()
        ks.search.return_value = [{"subdomain": "aca", "title": "x", "url": PAGE}]
        with mock.patch.object(search, "KeywordStore", return_value=ks), \
                mock.patch.object(search, "_judge_candidates", return_value={"good_enough": False, "reason": "no"}):
            evs, text = run_in_graph(lambda: search.search_texts.func({"rewritten": "q", "query": "q", "subdomain_hint": None}))
        self.assertIn("候選皆不相關", text)
        self.assertEqual((len(steps(evs, "group")), steps(evs, "row")), (2, []))                     # start + done, no rows

    def test_grep_emits_at_most_three_rows_and_keeps_its_text(self):
        from rag.agentic.tools import grep
        hits = [{"subdomain": "aca", "title": f"頁{i}", "url": f"https://aca.nccu.edu.tw/p{i}"} for i in range(5)]
        with mock.patch.object(grep, "_grep_texts_raw", return_value=hits):
            evs, text = run_in_graph(lambda: grep.grep_texts_tool.func("休學", {"subdomain_hint": None, "messages": []}))
        self.assertTrue(text.startswith("grep_texts('休學') 找到5筆"))
        self.assertEqual(len(steps(evs, "row")), 3)
        self.assertEqual(steps(evs, "group")[0]["verb"], "grep")


class TestPageTools(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"LIVE_FETCH": ""})
        self._env.start()
        self.hits = []
        hook._fetcher = Fetcher(limiter=RateLimiter(sleep=lambda s: None),
                                transport=httpx.MockTransport(lambda r: self.hits.append(1) or httpx.Response(200, content=HTML)), sleep=lambda s: None)
        from rag.agentic.tools import page as pg
        self.pg = pg
        self._raw = mock.patch.object(pg, "_get_page_raw", lambda url, subdomain=None: {"url": PAGE, "title": "休學", "subdomain": "aca", "text": "reg ext 62160"})
        self._raw.start()
        self._det = mock.patch.object(pg, "_detect_offices", lambda t: [])
        self._det.start()

    def tearDown(self):
        self._det.stop()
        self._raw.stop()
        self._env.stop()
        hook._fetcher = None

    def test_live_read_has_a_pending_row_then_the_result_and_the_text_is_unchanged(self):
        evs, text = run_in_graph(lambda: self.pg.get_page_tool.func(PAGE, {"live": True}))
        plain = self.pg.get_page_tool.func(PAGE, {"live": True})                    # outside any graph: no events, same text
        self.assertEqual(text, plain)
        self.assertEqual([(e["kind"], e["phase"]) for e in steps(evs)], [("group", "start"), ("row", "start"), ("row", "done"), ("group", "done")])
        start, done = steps(evs, "row")
        self.assertEqual((start["state"], done["state"], start["id"] == done["id"]), ("pending", "live_same", True))
        self.assertEqual((done["title"], done["host"], done["site_name"]), ("休學", "aca.nccu.edu.tw", "教務處"))
        self.assertTrue(done["time"])

    def test_live_off_leaves_one_database_row_and_no_request(self):
        evs, text = run_in_graph(lambda: self.pg.get_page_tool.func(PAGE, {"live": False}))
        rows = steps(evs, "row")
        self.assertEqual([(r["phase"], r["state"]) for r in rows], [("done", "snapshot")])
        self.assertEqual(self.hits, [])
        self.assertIn("status=snapshot", text)

    def test_cli_default_emits_the_same_way_and_leaves_the_text_as_before(self):
        evs, text = run_in_graph(lambda: self.pg.get_page_tool.func(PAGE, {}))
        self.assertEqual([(r["phase"], r["state"]) for r in steps(evs, "row")], [("done", "snapshot")])
        self.assertNotIn("[live:src", text)

    def test_a_page_not_in_the_corpus_is_a_group_without_rows(self):
        with mock.patch.object(self.pg, "_get_page_raw", lambda url, subdomain=None: {"error": "nf"}):
            evs, text = run_in_graph(lambda: self.pg.get_page_tool.func(PAGE, {"live": False}))
        self.assertEqual(text, "get_page 失敗: nf")
        self.assertEqual((len(steps(evs, "group")), steps(evs, "row")), (2, []))

    def test_extract_links_emits_a_links_group_with_the_page_row(self):
        evs, text = run_in_graph(lambda: self.pg.extract_links_tool.func(PAGE, {"live": True}))
        self.assertEqual(steps(evs, "group")[0]["verb"], "links")
        self.assertEqual([r["state"] for r in steps(evs, "row")], ["pending", "live_same"])
        self.assertEqual(text, "extract_links 找到 0 個連結")


class TestFormTools(unittest.TestCase):
    def setUp(self):
        from rag.agentic.tools import form as ft
        from rag.live import prefetch
        self.ft = ft
        snaps = {"QP-A": {"form_id": "QP-A", "form_title": "休學申請書", "text": "內文 QP-B", "url": "u"},
                 "QP-B": {"form_id": "QP-B", "form_title": "復學申請書", "text": "內文", "url": "u"}}
        self._p = [mock.patch.object(ft, "_get_form_raw", lambda fid: dict(snaps[fid])), mock.patch.object(ft, "get_store", lambda: prefetch.PrefetchStore())]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def test_single_form_group_takes_the_form_title(self):
        evs, text = run_in_graph(lambda: self.ft.get_form_tool.func("QP-A", {"live": False}))
        self.assertIn("休學申請書", text)
        grp_done = steps(evs, "group")[-1]
        self.assertEqual((grp_done["verb"], grp_done["title"]), ("form", "休學申請書"))
        (row,) = steps(evs, "row")
        self.assertEqual((row["row_kind"], row["state"], row["title"], row["url"]),
                         ("form", "snapshot", "休學申請書", "https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-A"))

    def test_resource_node_reads_all_its_forms_in_one_group(self):
        from rag.agentic.nodes import resource
        msgs = [ToolMessage(content="[偵測到表單編號: QP-T01-03-02, QP-T01-03-04]", tool_call_id="1")]
        snaps = {"QP-T01-03-02": {"form_id": "QP-T01-03-02", "form_title": "休學申請書", "text": "x", "url": "u"},
                 "QP-T01-03-04": {"form_id": "QP-T01-03-04", "form_title": "復學申請書", "text": "x", "url": "u"}}
        with mock.patch.object(self.ft, "_get_form_raw", lambda fid: dict(snaps[fid])), mock.patch.object(resource, "_detect_offices", return_value=[]):
            evs, out = run_in_graph(lambda: resource.resource_node({"query": "q", "subdomain_hint": "aca", "messages": msgs, "live": False}))
        groups = steps(evs, "group")
        self.assertEqual((len(groups), groups[-1]["title"]), (2, "休學申請書 …"))        # one block (start + done), refined from the first form
        self.assertEqual(len(steps(evs, "row")), 2)
        self.assertEqual({r["group_id"] for r in steps(evs, "row")}, {groups[0]["id"]})
        self.assertTrue(out["messages"][0].content.startswith("[表單全文"))


import test_live_p4_contacts as tc  # noqa: E402


class TestContacts(tc.Base):
    def test_every_staff_page_reports_from_its_worker_into_the_contacts_group(self):
        offices = ["註冊組", "教務長室", "國際合作事務處"]

        def work():
            with events.group("contacts", events.title_list(offices)) as g:
                self.run_chain(offices=offices)
                return g.id
        evs, gid = run_in_graph(work)
        rows = steps(evs, "row")
        done = [r for r in rows if r["phase"] == "done"]
        self.assertEqual(len(done), 3)
        self.assertEqual(len([r for r in rows if r["phase"] == "start"]), 3)
        self.assertTrue(all(r["group_id"] == gid for r in rows))
        self.assertEqual({r["site_name"] for r in done}, {"教務處", "國際合作事務處"})
        self.assertEqual({r["state"] for r in done}, {"live_changed"})
        self.assertTrue(all(r["time"] and r["seconds"] is not None and r["row_kind"] == "contact" for r in done))
        self.assertEqual({r["title"] for r in done}, {"註冊組 人員頁", "教務長室 人員頁", "國際合作事務處 人員頁"})   # one row per staff page
        order = [(e["kind"], e["phase"]) for e in steps(evs)]
        self.assertEqual((order[0], order[-1]), (("group", "start"), ("group", "done")))

    def test_contact_node_with_live_off_lists_the_pages_read_and_fixed_data(self):
        import rag.agentic.nodes.contact as cn
        skill = mock.Mock()
        skill.run.return_value = {"註冊組": {"contacts_source": "page", "page_url": self.url("註冊組")},
                                  "國際合作事務處": {"contacts_source": "known_contacts", "page_url": None}}
        skill.format_context.return_value = "[contacts body]"
        state = {"query": "q", "messages": [HumanMessage(content="x")], "live": False}
        with mock.patch.object(cn, "_detect_offices", return_value=["註冊組", "國際合作事務處"]), \
                mock.patch("rag.skills.office_lookup_skill.OfficeLookupSkill", return_value=skill), \
                mock.patch("rag.live.contacts.fetch_contact_pages") as fetch, mock.patch.dict(os.environ, {"LIVE_FETCH": ""}):
            evs, out = run_in_graph(lambda: cn.contact_node(state))
        fetch.assert_not_called()
        rows = steps(evs, "row")
        self.assertEqual([(r["state"], r["row_kind"]) for r in rows], [("snapshot", "contact"), ("fixed_data", "contact")])
        self.assertEqual(rows[1]["url"], "")
        self.assertEqual(steps(evs, "group")[0]["verb"], "contacts")


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server

    def run_pump(self, fake_graph):
        async def go():
            q = asyncio.Queue()
            with mock.patch.object(self.server, "_graph", fake_graph):
                await self.server._pump("q", None, None, {"configurable": {"thread_id": "t"}}, q)
            out = []
            while not q.empty():
                out.append(q.get_nowait())
            return out
        return asyncio.run(go())

    def fake(self, final_values=None, raise_in_state=False, raise_in_stream=False):
        marker = ledger.make_marker(PAGE, "live_same", "2026-10-17T14:31", "2026-08-19", title="休學")
        values = final_values if final_values is not None else {
            "messages": [ToolMessage(content="get_page 取得 5 字\n" + marker + "\n\n全文：\nx", tool_call_id="1")], "live": True}

        class G:
            async def astream(self, state, config=None, stream_mode=None):
                assert "custom" in stream_mode
                yield "custom", {"type": "step", "kind": "group", "id": "g1", "verb": "page", "title": "休學", "phase": "start"}
                yield "custom", {"no": "type"}                                     # not an event: ignored
                yield "messages", (AIMessageChunk(content="答"), {"langgraph_node": "synthesis_node"})
                yield "updates", {"synthesis_node": {"answer": "答\n\n---\n【資料狀態】（由系統依實際抓取結果產生）\n- x"}}
                if raise_in_stream:
                    raise RuntimeError("graph blew up")

            async def aget_state(self, config):
                if raise_in_state:
                    raise RuntimeError("no state")
                return SimpleNamespace(values=values)
        return G()

    def test_events_are_forwarded_the_footer_is_not_streamed_and_sources_come_last(self):
        items = self.run_pump(self.fake())
        self.assertIn({"type": "step", "kind": "group", "id": "g1", "verb": "page", "title": "休學", "phase": "start"}, items)
        self.assertNotIn({"no": "type"}, items)
        self.assertIn({"data": "答"}, items)
        self.assertFalse(any(isinstance(i, dict) and "資料狀態" in str(i.get("data", "")) for i in items), "the footer must not be streamed as answer text")
        last = items[-2] if items[-1] is self.server._STREAM_DONE else items[-1]
        self.assertEqual(items[-1], self.server._STREAM_DONE)
        self.assertEqual(last["type"], "sources")
        self.assertTrue(last["live"])
        self.assertEqual([(g["name"], g["items"][0]["state"]) for g in last["groups"]], [("教務處", "live_same")])

    def test_a_failure_building_the_sources_does_not_spoil_the_answer(self):
        items = self.run_pump(self.fake(raise_in_state=True))
        self.assertIn({"data": "答"}, items)
        self.assertFalse(any(isinstance(i, dict) and i.get("type") == "sources" for i in items))
        self.assertFalse(any(isinstance(i, Exception) for i in items))
        self.assertEqual(items[-1], self.server._STREAM_DONE)

    def test_a_graph_error_still_goes_to_the_error_path_with_no_sources(self):
        items = self.run_pump(self.fake(raise_in_stream=True))
        self.assertTrue(any(isinstance(i, RuntimeError) for i in items))
        self.assertFalse(any(isinstance(i, dict) and i.get("type") == "sources" for i in items))

    def test_live_off_is_reported_in_the_sources_event(self):
        items = self.run_pump(self.fake({"messages": [], "live": False}))
        (src,) = [i for i in items if isinstance(i, dict) and i.get("type") == "sources"]
        self.assertEqual((src["live"], src["groups"]), (False, []))


if __name__ == "__main__":
    unittest.main()
