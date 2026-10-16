"""
Offline tests for P4 step 5: contact_node + OfficeLookupSkill read the staff pages live when LIVE_FETCH=on, and are
unchanged when it is off. The browser is the fake from test_live_p4_contacts (recorded pages, fake clock); the LLM page
parse is stubbed and counted. No Chromium, no network, no LLM.
    python -W ignore -m unittest experiments.live_spikes.test_live_p4_node -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import test_live_p4_contacts as tc  # noqa: E402  (PagesOwner, Base, OFFICES)
import test_live_p4_schedule as sch  # noqa: E402
import rag.agentic.nodes.contact as cn  # noqa: E402
import rag.live.contacts as lc  # noqa: E402
import rag.skills.office_lookup_skill as sk  # noqa: E402
from rag.live.browser import RenderResult  # noqa: E402
from rag.live.schedule import RenderScheduler  # noqa: E402

OFFICES = tc.OFFICES


def strip_ledger(text: str) -> str:
    """Drop the ledger section contact_node appends in `on` mode (it starts after a blank line with a marker line)."""
    cuts = [i for i in (text.find("\n\n[live:src"), text.find("\n\n[contacts:")) if i >= 0]
    return text[:min(cuts)] if cuts else text


class NodeBase(tc.Base):
    def setUp(self):
        super().setUp()
        self.llm_texts: list[str] = []
        self._p.stop()                                           # replace Base's stub with one that keeps the text
        self._p = mock.patch.object(sk, "_llm_extract_contacts", lambda t: self.llm_texts.append(t) or [])
        self._p.start()
        self._d = mock.patch.object(cn, "_detect_offices", return_value=OFFICES)
        self._d.start()
        self._env = mock.patch.dict(os.environ, {"LIVE_FETCH": "off"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._d.stop()
        super().tearDown()

    def node(self) -> str:
        return cn.contact_node({"query": "q", "messages": [HumanMessage(content="x")]})["messages"][0].content

    def live_node(self, override=None, scheduler_raises=False) -> str:
        owner = tc.PagesOwner(self.clock, self.limiter, self.pages, override)
        sched = RenderScheduler(owner.render, self.limiter)

        def make():
            if scheduler_raises:
                raise RuntimeError("chromium is not installed")
            return sched
        with mock.patch.dict(os.environ, {"LIVE_FETCH": "on"}), mock.patch.object(lc, "default_scheduler", make):
            return self.node()


class TestOffIsUnchanged(NodeBase):
    def test_off_never_touches_the_live_path_and_matches_the_plain_skill(self):
        with mock.patch.object(lc, "fetch_contact_pages", side_effect=AssertionError("live path used while off")):
            out = self.node()
        direct = sk.OfficeLookupSkill()
        expected_body = direct.format_context(direct.run(OFFICES))
        self.assertTrue(out.endswith(expected_body))


class TestOn(NodeBase):
    def test_the_departed_person_is_gone_and_the_dean_is_still_there(self):
        off, on = self.node(), self.live_node()
        self.assertIn("62442", off)
        self.assertNotIn("62442", on)
        self.assertIn("62160", on)

    def test_no_page_is_parsed_twice(self):
        self.live_node()
        self.assertEqual(len(self.llm_texts), len(set(self.llm_texts)),
                         "the same page text went to the LLM reader more than once")

    def test_every_page_the_pipeline_parsed_is_reused_not_reparsed(self):
        self.live_node()
        on_calls = len(self.llm_texts)
        self.llm_texts.clear()
        self.node()                                              # off: the index path parses each page once
        self.assertLessEqual(on_calls, len(self.llm_texts) + 1)   # live may add at most oic's newly-named page

    def test_when_every_render_fails_the_answer_is_the_snapshot_answer(self):
        fail = {u: (lambda uu: RenderResult(uu, error="timeout", detail="x")) for u, _ in self.page_of.values()}
        self.assertEqual(strip_ledger(self.live_node(override=fail)), self.node())

    def test_when_the_live_machinery_itself_breaks_the_answer_is_the_snapshot_answer(self):
        self.assertEqual(strip_ledger(self.live_node(scheduler_raises=True)), self.node())

    def test_an_office_the_index_does_not_cover_still_gets_its_snapshot_answer(self):
        offices = ["教務長室", "不存在的處室"]
        with mock.patch.object(cn, "_detect_offices", return_value=offices):
            off, on = self.node(), self.live_node()
        line = lambda t: next(l for l in t.splitlines() if l.strip().startswith("不存在的處室"))
        self.assertEqual(line(on), line(off))


class TestParsedBypass(NodeBase):
    def test_parsed_contacts_are_used_as_given(self):
        url = self.page_of["教務長室"][0]
        sentinel = [{"name": "測試", "ext": "99999", "email": None, "duty": "x"}]
        contacts, urls = sk.dynamic_contacts_for_office("教務長室", parsed={url: sentinel})
        self.assertEqual((contacts, urls), (sentinel, [url]))

    def test_without_parsed_nothing_changes(self):
        self.assertEqual(sk.dynamic_contacts_for_office("教務長室", parsed=None), sk.dynamic_contacts_for_office("教務長室"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
