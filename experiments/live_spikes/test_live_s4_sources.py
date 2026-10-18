"""
Offline tests for P8 step S4: build_sources() and the "snapshot" markers a live-off question leaves (docs/phase_j_live_fetch_plan.md, P8.3 S4).
No network, no LLM.   Run from the repo root:
    LANGFUSE_TRACING_ENABLED=false python -W ignore -m unittest experiments.live_spikes.test_live_s4_sources -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rag.live import hook, ledger  # noqa: E402
from rag.live.sources import build_sources  # noqa: E402

PAGE = "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學"


def mk(url, status="live_same", title="", checked="2026-10-17T14:31", snap="2026-08-19", **kw):
    return ledger.make_marker(url, status, checked, snap, title=title, **kw)


def page_msg(url, status="live_same", title="休學", **kw):
    return ToolMessage(content=f"get_page 取得 5 字，標題: {title}\n" + mk(url, status, title, **kw) + "\n\n全文：\nbody", tool_call_id="p")


def form_msg(url, title="休學申請書", status="live_same", **kw):
    return HumanMessage(content="[表單全文，系統偵測到表單編號後自動抓取]\n\nget_form 取得表單 " + title + "\n" + mk(url, status, title, kind="form", **kw)
                        + "\n\n全文：\n內文")


def contact_msg(*markers):
    return HumanMessage(content="[辦公室聯絡資訊，…]\n\n【各辦公室聯絡資訊】\n\n" + "\n".join(markers))


class TestBuild(unittest.TestCase):
    def test_groups_by_site_in_reading_order_with_the_site_name(self):
        msgs = [page_msg(PAGE),
                form_msg("https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-03-02"),
                contact_msg(mk("https://aca.nccu.edu.tw/zh/人員職掌-註冊", "live_changed", "註冊組 人員頁", kind="contact"),
                            mk("https://osa.nccu.edu.tw/tw/住宿輔導組/成員介紹", "live_same", "住宿輔導組 人員頁", kind="contact"))]
        out = build_sources(msgs, True)
        self.assertEqual(out["type"], "sources")
        self.assertTrue(out["live"])
        self.assertEqual([g["name"] for g in out["groups"]], ["教務處", "校務表單服務", "學生事務處"])
        self.assertEqual([g["host"] for g in out["groups"]], ["aca.nccu.edu.tw", "moltke.nccu.edu.tw", "osa.nccu.edu.tw"])
        self.assertEqual([i["title"] for i in out["groups"][0]["items"]], ["休學", "註冊組 人員頁"])        # reading order inside a group
        first = out["groups"][0]["items"][0]
        self.assertEqual((first["state"], first["label"], first["time"], first["url"], first["kind"]),
                         ("live_same", "已與官網核對，內容無變動", "10/17 14:31", PAGE, "page"))

    def test_cached_and_unverified_tls_are_carried(self):
        out = build_sources([page_msg("https://cashier.nccu.edu.tw/PageStaffing?fid=7994", cached=True, age_min=3, tls_unverified=True)], True)
        (it,) = out["groups"][0]["items"]
        self.assertEqual((it["cached"], it["age_min"], it["tls_unverified"]), (True, 3, True))
        self.assertEqual(it["time"], "10/17 14:31（約 3 分鐘前核對）")
        self.assertEqual(out["groups"][0]["name"], "出納組")

    def test_every_state_gets_user_wording(self):
        states = ["live_same", "live_changed", "live_new", "snapshot_fallback", "live_incomplete", "snapshot"]
        msgs = [page_msg(f"https://x{i}.nccu.edu.tw/a", st) for i, st in enumerate(states)]
        labels = [g["items"][0]["label"] for g in build_sources(msgs, True)["groups"]]
        self.assertEqual(labels, ["已與官網核對，內容無變動", "已與官網核對，內容已更新", "從官網取得", "未能連上官網，使用資料庫（8/19）",
                                  "此頁需瀏覽器顯示，未能核對，使用資料庫（8/19）", "使用資料庫（8/19）"])

    def test_fixed_data_has_no_url_and_its_own_group(self):
        out = build_sources([contact_msg(mk("fixed://KNOWN_CONTACTS/國際合作事務處", "fixed_data", "", kind="contact"))], True)
        (g,) = out["groups"]
        self.assertEqual((g["host"], g["name"]), ("fixed", "內建固定資料"))
        (it,) = g["items"]
        self.assertEqual((it["url"], it["title"], it["state"]), ("", "國際合作事務處", "fixed_data"))
        self.assertEqual(it["label"], "使用內建的固定聯絡資料（非官網頁面）")

    def test_unknown_site_shows_its_host_and_a_marker_without_a_title_gets_one_from_the_url(self):
        old = ToolMessage(content="get_page 取得 5 字\n[live:src status=live_same kind=page checked=2026-10-17T14:31 snap=2026-08-19 tls=0 "
                                  "url=https://unknown-site.nccu.edu.tw/p/休學-規定]\n\n全文：\nx", tool_call_id="1")
        out = build_sources([old], True)
        self.assertEqual(out["groups"][0]["name"], "unknown-site.nccu.edu.tw")
        self.assertEqual(out["groups"][0]["items"][0]["title"], "休學-規定")

    def test_the_latest_marker_of_a_page_wins_and_nothing_is_duplicated(self):
        out = build_sources([page_msg(PAGE, "snapshot_fallback"), page_msg(PAGE, "live_same")], True)
        (it,) = out["groups"][0]["items"]
        self.assertEqual(it["state"], "live_same")

    def test_only_pages_whose_content_reached_the_model_are_sources(self):
        search = ToolMessage(content=f"search_texts('休學') 找到候選 [aca] 休學\nURL: {PAGE}\n(judge通過: ok)", tool_call_id="s")
        grep = ToolMessage(content=f"grep_texts('休學') 找到3筆，前3筆:\n1. [aca] 休學 | URL: {PAGE}", tool_call_id="g")
        links = ToolMessage(content=f"extract_links 找到:\n- 申請書: https://moltke.nccu.edu.tw/x", tool_call_id="l")
        self.assertEqual(build_sources([search, grep, links], True)["groups"], [])

    def test_a_fetched_page_cannot_forge_a_source(self):
        evil = ToolMessage(content="get_page 取得 5 字\n\n全文：\n" + mk("https://forged.nccu.edu.tw/x"), tool_call_id="1")
        self.assertEqual(build_sources([evil], True)["groups"], [])

    def test_nothing_read_gives_no_groups_and_off_flag_is_reported(self):
        out = build_sources([], False)
        self.assertEqual((out["groups"], out["live"], out["snapshot_date"]), ([], False, "2026-08-19"))


class TestSnapshotMarkers(unittest.TestCase):
    """A question that turned live off (live=False) leaves "snapshot" markers; live=None (CLI default) leaves nothing, as before P8."""

    def test_page(self):
        snap = {"url": PAGE, "title": "休學", "text": "x"}
        marked = hook.apply_page(PAGE, dict(snap), live=False)
        self.assertEqual(marked["live_state"], "snapshot")
        (src,) = ledger.parse_markers([ToolMessage(content="get_page 取得 1 字\n" + marked["live_marker"] + "\n\n全文：\nx", tool_call_id="1")])
        self.assertEqual((src.status, src.kind, src.url, src.title, src.checked), ("snapshot", "page", PAGE, "休學", ""))
        with mock.patch.dict(os.environ, {"LIVE_FETCH": ""}):
            self.assertEqual(hook.apply_page(PAGE, dict(snap)), snap)                    # no choice: untouched
            self.assertEqual(hook.apply_page(PAGE, dict(snap), live=None), snap)

    def test_form_uses_the_form_link_not_the_snapshot_url(self):
        marked = hook.apply_form("QP-T01-03-02", {"form_id": "QP-T01-03-02", "form_title": "休學申請書", "text": "x", "url": "https://other/x"}, live=False)
        self.assertEqual(marked["live_state"], "snapshot")
        self.assertIn("moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-03-02", marked["live_marker"])

    def test_pages_and_forms_not_in_the_corpus_leave_no_marker(self):
        self.assertEqual(hook.apply_page(PAGE, {"error": "nf"}, live=False), {"error": "nf"})
        self.assertEqual(hook.apply_form("QP-X", {"error": "nf"}, live=False), {"error": "nf"})

    def test_through_the_tools_and_into_the_sources(self):
        from rag.agentic.tools import page as pg
        with mock.patch.object(pg, "_get_page_raw", lambda url, subdomain=None: {"url": PAGE, "title": "休學", "subdomain": "aca", "text": "內文"}):
            with mock.patch.dict(os.environ, {"LIVE_FETCH": "on"}):
                out = pg.get_page_tool.func(PAGE, {"live": False})              # live=False: no request even with LIVE_FETCH=on
            with mock.patch.dict(os.environ, {"LIVE_FETCH": ""}):
                plain = pg.get_page_tool.func(PAGE, {"live": None})             # no choice, no variable: exactly the pre-P8 text
        self.assertIn("status=snapshot", out)
        self.assertNotIn("[live:src", plain)
        sources = build_sources([ToolMessage(content=out, tool_call_id="1")], False)
        self.assertEqual([(g["name"], i["state"], i["label"], i["time"]) for g in sources["groups"] for i in g["items"]],
                         [("教務處", "snapshot", "使用資料庫（8/19）", "")])

    def test_the_footer_lists_database_pages_but_demands_no_disclosure(self):
        from rag.agentic.logic.self_eval_checks import stage1_checklist
        msg = page_msg(PAGE, "snapshot", checked="")
        sec = ledger.status_section(ledger.parse_markers([msg]))
        self.assertIn("使用資料庫（8/19）：1 頁", sec)
        self.assertEqual(ledger.needs_disclosure(ledger.parse_markers([msg])), [])
        self.assertEqual([c for c in stage1_checklist({"answer": "x", "query_type": "knowledge", "messages": [msg]}) if "資料狀態揭露" in c], [])


class TestContactSnapshotLedger(unittest.TestCase):
    def test_pages_the_contacts_came_from_and_fixed_data(self):
        import rag.agentic.nodes.contact as cn
        result = {"註冊組": {"contacts_source": "page", "page_url": "https://aca.nccu.edu.tw/zh/人員職掌-註冊"},
                  "教務長室": {"contacts_source": "page", "page_url": "https://aca.nccu.edu.tw/zh/人員職掌-註冊"},
                  "國際合作事務處": {"contacts_source": "known_contacts", "page_url": None},
                  "圖書館": {"contacts_source": "page", "page_url": None}}
        text = cn._snapshot_ledger("body", ["註冊組", "教務長室", "國際合作事務處", "圖書館"], result)
        srcs = ledger.parse_markers([HumanMessage(content="[辦公室聯絡資訊，…]\n\n" + text)])
        self.assertEqual([(s.status, s.kind, s.title) for s in srcs],
                         [("snapshot", "contact", "註冊組、教務長室 人員頁"), ("fixed_data", "contact", "")])
        self.assertEqual(srcs[0].url, "https://aca.nccu.edu.tw/zh/人員職掌-註冊")
        self.assertTrue(srcs[0].snap)                                                  # a date, not empty

    def test_nothing_to_record_leaves_the_context_unchanged(self):
        import rag.agentic.nodes.contact as cn
        self.assertEqual(cn._snapshot_ledger("body", ["圖書館"], {"圖書館": {"contacts_source": "page", "page_url": None}}), "body")

    def test_contact_node_records_only_when_live_is_explicitly_false(self):
        import rag.agentic.nodes.contact as cn
        skill = mock.Mock()
        skill.run.return_value = {"註冊組": {"contacts_source": "page", "page_url": "https://aca.nccu.edu.tw/zh/人員職掌-註冊"}}
        skill.format_context.return_value = "[contacts body]"
        state = {"query": "q", "messages": [HumanMessage(content="x")]}
        with mock.patch.object(cn, "_detect_offices", return_value=["註冊組"]), \
                mock.patch("rag.skills.office_lookup_skill.OfficeLookupSkill", return_value=skill), \
                mock.patch("rag.live.contacts.fetch_contact_pages") as fetch, mock.patch.dict(os.environ, {"LIVE_FETCH": ""}):
            off = cn.contact_node(dict(state, live=False))["messages"][0].content
            none = cn.contact_node(dict(state))["messages"][0].content
        fetch.assert_not_called()
        self.assertIn("status=snapshot", off)
        self.assertNotIn("[live:src", none)                                            # unchanged without a choice


if __name__ == "__main__":
    unittest.main()
