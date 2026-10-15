"""
Offline tests for rag/agentic/logic/form_gate.py (P3.5). The LLM is a stub: these test the plumbing and the
fail-open rules, NOT how well the real model judges (that is run_gate_eval.py's job, with real calls).
    python -W ignore -m unittest experiments.form_gate.test_form_gate -v
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from langchain_core.messages import ToolMessage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rag.agentic.logic import form_gate as fg  # noqa: E402

IDS = ["QP-T01-03-02", "QP-T01-03-04", "QP-T01-02-05"]
TOOL_TEXT = ("get_page 取得 120 字，標題: 休學，subdomain: aca\n"
             "[live:src status=live_same kind=page checked=x snap=x tls=0 url=https://aca.nccu.edu.tw/a]\n"
             "[偵測到表單編號: QP-T01-02-05, QP-T01-03-02, QP-T01-03-04]\n\n全文：\n休學請填 QP-T01-03-02。提早復學請填 QP-T01-03-04。")


def reply(**fetch):
    return json.dumps({"forms": [{"id": k.replace("_", "-"), "fetch": v, "reason": "r"} for k, v in fetch.items()]})


class TestClean(unittest.TestCase):
    def test_strips_system_lines_keeps_page(self):
        out = fg.clean_page_text(TOOL_TEXT)
        self.assertEqual(out, "休學請填 QP-T01-03-02。提早復學請填 QP-T01-03-04。")

    def test_text_without_header_unchanged(self):
        self.assertEqual(fg.clean_page_text("純頁面文字"), "純頁面文字")


class TestSelect(unittest.TestCase):
    def run_gate(self, llm, ids=IDS):
        return fg.select_forms("如何辦理休學", TOOL_TEXT, ids, llm=llm)

    def test_explicit_false_is_skipped(self):
        r = self.run_gate(lambda p: reply(QP_T01_03_02=True, QP_T01_03_04=False, QP_T01_02_05=True))
        self.assertEqual(r.fetch_ids, ["QP-T01-03-02", "QP-T01-02-05"])
        self.assertEqual(list(r.skipped), ["QP-T01-03-04"])
        self.assertFalse(r.fell_back)

    def test_omitted_id_is_still_fetched(self):
        r = self.run_gate(lambda p: reply(QP_T01_03_02=True))
        self.assertEqual(r.fetch_ids, IDS)

    def test_string_false_is_not_an_exclusion(self):
        bad = json.dumps({"forms": [{"id": "QP-T01-03-04", "fetch": "false", "reason": "x"}]})
        self.assertEqual(self.run_gate(lambda p: bad).fetch_ids, IDS)

    def test_unknown_id_ignored(self):
        r = self.run_gate(lambda p: reply(QP_X_9_9=False, QP_T01_03_04=False))
        self.assertEqual(r.fetch_ids, ["QP-T01-03-02", "QP-T01-02-05"])

    def test_json_wrapped_in_prose_and_fences(self):
        r = self.run_gate(lambda p: "好的：\n```json\n" + reply(QP_T01_03_04=False) + "\n```")
        self.assertEqual(r.skipped.keys(), {"QP-T01-03-04"})

    def test_malformed_reply_fetches_all(self):
        for bad in ("無", "", "QP-T01-03-02", "{not json", '{"forms": "x"}', '{"other": []}'):
            r = self.run_gate(lambda p, b=bad: b)
            self.assertEqual((r.fetch_ids, r.fell_back), (IDS, True), repr(bad))

    def test_exception_fetches_all(self):
        def boom(p):
            raise TimeoutError("x")
        r = self.run_gate(boom)
        self.assertEqual((r.fetch_ids, r.fell_back), (IDS, True))

    def test_excluding_everything_fetches_all(self):
        r = self.run_gate(lambda p: reply(QP_T01_03_02=False, QP_T01_03_04=False, QP_T01_02_05=False))
        self.assertEqual((r.fetch_ids, r.fell_back), (IDS, True))

    def test_single_candidate_makes_no_llm_call(self):
        r = self.run_gate(lambda p: self.fail("LLM must not run"), ids=["QP-T01-03-02"])
        self.assertEqual(r.fetch_ids, ["QP-T01-03-02"])

    def test_prompt_has_page_text_but_no_system_lines(self):
        seen = {}
        self.run_gate(lambda p: seen.setdefault("p", p) and reply())
        p = seen["p"]
        self.assertIn("提早復學請填 QP-T01-03-04", p)
        self.assertNotIn("get_page 取得", p)
        self.assertNotIn("[live:src", p)
        self.assertNotIn("[偵測到表單編號", p)
        self.assertIn("如何辦理休學", p)

    def test_duplicate_candidates_collapsed(self):
        r = self.run_gate(lambda p: reply(), ids=IDS + IDS)
        self.assertEqual(r.fetch_ids, IDS)


class TestResourceNodeWiring(unittest.TestCase):
    def _run(self, gate_env, gate_result=None):
        from rag.agentic.nodes import resource
        tool = mock.Mock()
        tool.invoke.side_effect = lambda a: f"get_form 取得表單 {a['form_id']}\n\nbody"
        state = {"query": "如何辦理休學", "subdomain_hint": "aca", "messages": [ToolMessage(content=TOOL_TEXT, tool_call_id="1")]}
        env = {"FORM_GATE": gate_env}
        with mock.patch.dict(os.environ, env), mock.patch.object(resource, "get_form_tool", tool), \
                mock.patch.object(resource, "_detect_offices", return_value=[]), \
                mock.patch.object(resource, "select_forms", return_value=gate_result) as sel:
            resource.resource_node(state)
        return [c.args[0]["form_id"] for c in tool.invoke.call_args_list], sel

    def test_gate_off_fetches_every_detected_form_and_never_calls_gate(self):
        fetched, sel = self._run("off", fg.GateResult(["QP-T01-03-02"]))
        self.assertEqual(sorted(fetched), sorted(IDS))
        sel.assert_not_called()

    def test_gate_on_fetches_only_selected(self):
        fetched, sel = self._run("on", fg.GateResult(["QP-T01-03-02", "QP-T01-02-05"], {"QP-T01-03-04": "r"}))
        self.assertEqual(sorted(fetched), ["QP-T01-02-05", "QP-T01-03-02"])
        sel.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
