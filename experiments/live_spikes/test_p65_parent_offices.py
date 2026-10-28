"""
Offline checks for P6.5 (docs/phase_j_live_fetch_plan.md): a parent unit (教務處, 學生事務處) whose index page is a site home page reads the
next 1-2 sibling staff pages instead; a parent named only in page text is skipped; the direct CONTACT route scans the new question on every
turn; stray spaces inside a unit name no longer hide it. Fake fetcher, fake browser, the LLM judge answers "無": no network, no LLM.
The real office index (output/office_contacts_index.jsonl) is read as it is.   Run from the repo root:
    LANGFUSE_TRACING_ENABLED=false python -W ignore -m unittest experiments.live_spikes.test_p65_parent_offices -v
"""

from __future__ import annotations

import sys
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest import mock

from langchain_core.messages import AIMessage, HumanMessage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rag.agentic.logic import office_detection  # noqa: E402
from rag.agentic.nodes import contact  # noqa: E402
from rag.live.browser import RenderResult  # noqa: E402
from rag.live.fetcher import LiveResult  # noqa: E402
from rag.skills import office_lookup_skill as skill_mod  # noqa: E402


class Fakes:
    """Serves each index page's own text as its 'live' page, and records what was asked for."""

    def __init__(self, texts: dict[str, str]):
        self.texts, self.fetched, self.rendered = texts, [], []

    def fetch_static(self, url: str) -> LiveResult:
        self.fetched.append(url)
        return LiveResult(url, ok=True, final_url=url, status=200, text=self.texts.get(url, ""), fetched_at=time.time(), attempts=1)

    def render(self, url: str) -> Future:
        self.rendered.append(url)
        f: Future = Future()
        f.set_result(RenderResult(url, error="render_error", detail="fake browser"))
        return f


def _state(query: str, **kw) -> dict:
    return {"query": query, "messages": [], "query_type": "contact", "turn": 0, "live": True, **kw}


class P65Base(unittest.TestCase):
    def setUp(self):
        self._saved_cache = skill_mod._contacts_index_cache
        skill_mod._contacts_index_cache = None
        idx = skill_mod._load_contacts_index()
        self.index_texts = {r["url"]: r["text"] for recs in idx.values() for r in recs}
        self.url = {r["name"]: r["url"] for recs in idx.values() for r in recs}
        self.fakes = Fakes(self.index_texts)
        self.patches = [
            mock.patch.object(office_detection, "simple_chat", lambda **kw: "無"),          # the LLM judge finds nothing
            mock.patch.object(skill_mod, "_llm_extract_contacts", lambda text: []),         # no LLM re-read of a page
            mock.patch("rag.live.contacts.default_backends", lambda: (self.fakes.fetch_static, self.fakes.render)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        skill_mod._contacts_index_cache = self._saved_cache

    def run_node(self, state: dict) -> str:
        out = contact.contact_node(state)
        return out["messages"][0].content if out else ""

    def use_index(self, index: dict[str, list[dict]]):
        """A tiny synthetic index instead of the real one (the fakes serve its pages)."""
        skill_mod._contacts_index_cache = index
        self.fakes.texts = {r["url"]: r["text"] for recs in index.values() for r in recs}


class ParentFromTheQuestion(P65Base):
    def test_教務處_reads_the_first_children_not_the_home_page(self):
        text = self.run_node(_state("教務處的聯絡人是誰"))
        self.assertEqual(sorted(self.fakes.fetched), sorted(self.url[n] for n in ("教務長室", "註冊組", "課務組")))     # one batch of PARENT_BATCH_SIZE (3); the pages of a batch go out together, so their order is not fixed
        self.assertNotIn(self.url["教務處"], self.fakes.fetched)                             # the 9-character home page is not read
        self.assertEqual(self.fakes.rendered, [])                                            # and no Chromium render is wasted on it
        self.assertIn("劉吉軒", text)
        self.assertIn("「教務處」是網站首頁、沒有人員資料，改讀同網站的教務長室", text)
        self.assertNotIn("內建的固定資料", text)

    def test_學生事務處_reads_one_batch_of_three_and_stops(self):
        text = self.run_node(_state("學生事務處的聯絡人"))
        self.assertEqual(sorted(self.fakes.fetched), sorted(self.url[n] for n in ("學務長室(學務長)", "學務長室(副學務長)", "學務長室(中心與成員)")))   # one batch of 3, then stop
        self.assertIn("蔡炎龍", text)
        self.assertNotIn("職涯講座", text)                                                   # the home page's made-up "contact" is gone

    def test_children_without_contacts_fall_back_to_the_parent_then_KNOWN_CONTACTS(self):
        rec = lambda name, url, text="": {"name": name, "url": url, "text": text, "category": "", "subdomain": "aca.nccu.edu.tw", "fetched_at": ""}
        self.use_index({
            "教務處": [rec("教務處", "https://aca.nccu.edu.tw", "國立政治大學教務處")],
            "教務長室": [rec("教務長室", "https://aca.nccu.edu.tw/a", "簡介")],
            "註冊組": [rec("註冊組", "https://aca.nccu.edu.tw/b", "簡介")],
            "課務組": [rec("課務組", "https://aca.nccu.edu.tw/c", "簡介")],
        })
        text = self.run_node(_state("教務處電話"))
        # one batch of the 3 children first, the parent's own page last, in that order
        self.assertEqual(sorted(self.fakes.fetched[:3]), ["https://aca.nccu.edu.tw/a", "https://aca.nccu.edu.tw/b", "https://aca.nccu.edu.tw/c"])
        self.assertEqual(self.fakes.fetched[-1], "https://aca.nccu.edu.tw")
        self.assertIn("同網站的 3 個子單位頁面都沒有解析到人員", text)
        self.assertIn("劉吉軒", text)                                                         # KNOWN_CONTACTS["教務處"], the last resort
        self.assertIn("status=fixed_data kind=contact", text)                                # and the ledger says so (the UI words it later)
        self.assertIn("fixed://KNOWN_CONTACTS/教務處", text)

    def test_no_parent_means_no_expansion_and_the_old_output(self):
        state = _state("出納組電話幾號", live=None)
        text = self.run_node(state)
        skill = skill_mod.OfficeLookupSkill()
        want_header = ("[辦公室聯絡資訊，以下是內容中提及的全部 1 個辦公室（出納組），未經相關性篩選——這是完整清單，不代表每一個都跟這題直接相關。"
                       "是否每個都要寫進最終答案由你根據問題判斷，不要假設清單已經先篩過。]")
        self.assertEqual(text, want_header + "\n\n" + skill.format_context(skill.run(["出納組"])))


class ParentFromPageText(P65Base):
    def test_a_bare_parent_in_a_page_is_skipped(self):
        page = HumanMessage(content="詳情請至教務處網頁公告查看。")
        out = contact.contact_node({"query": "怎麼辦理休學", "messages": [page], "query_type": "knowledge", "turn": 1, "live": True})
        self.assertEqual(out, {})
        self.assertEqual(self.fakes.fetched, [])

    def test_a_parent_named_next_to_its_own_child_is_not_looked_up_twice(self):
        page = HumanMessage(content="請洽教務處，或註冊組承辦人。")
        out = contact.contact_node({"query": "怎麼辦理休學", "messages": [page], "query_type": "knowledge", "turn": 1, "live": True})
        self.assertEqual(self.fakes.fetched, [self.url["註冊組"]])
        self.assertNotIn("改讀同網站", out["messages"][0].content)


class DirectRouteScansTheQuestion(P65Base):
    def test_second_turn_scans_the_new_question_not_the_previous_answer(self):
        seen = []
        with mock.patch.object(contact, "_detect_offices", lambda text: seen.append(text) or ["出納組"]):
            state = _state("那出納組電話呢", live=False)
            state["messages"] = [HumanMessage(content="如何辦理休學"), AIMessage(content="請洽註冊組辦理。")]    # turn 1's [question, answer]
            contact.contact_node(state)
            self.assertEqual(seen, ["那出納組電話呢"])
            seen.clear()
            tool_turn = _state("那出納組電話呢", live=False, query_type="knowledge", turn=2)                   # a marker after a tool: the page text
            tool_turn["messages"] = [HumanMessage(content="頁面內容：請洽註冊組")]
            contact.contact_node(tool_turn)
            self.assertEqual(seen, ["頁面內容：請洽註冊組"])


class StraySpaces(P65Base):
    def test_a_space_inside_a_unit_name_no_longer_leaves_the_parent_behind(self):
        self.assertEqual(office_detection._detect_offices("送教務處註冊 組協助辦理"), ["註冊組"])
        self.assertEqual(office_detection._detect_offices("請至教務處網頁"), ["教務處"])          # unchanged
        self.assertEqual(office_detection._squeeze_cjk_gaps("Office hour 與 IMBA 學程"), "Office hour 與 IMBA 學程")


if __name__ == "__main__":
    unittest.main()
