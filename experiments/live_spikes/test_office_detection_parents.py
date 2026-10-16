"""
Tests for rag.agentic.logic.office_detection._drop_qualifier_parents (parent written in front of its child: 教務處註冊組).
The LLM judge is stubbed; the catalog is the real one for the 休學-chain check and a small fake one elsewhere.
    python -W ignore -m unittest experiments.live_spikes.test_office_detection_parents -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import rag.agentic.logic.office_detection as od  # noqa: E402

FIX = ROOT / "experiments" / "live_fixtures" / "chain_xiuxue_2026-10-14"
SMALL = [("教務處", "aca"), ("註冊組", "aca"), ("總務處", "ga"), ("出納組", "cashier"), ("圖書館", "lib"), ("教務長室", "aca")]


def detect(text, llm="無", catalog=SMALL):
    with mock.patch.object(od, "_keyword_table", lambda: catalog), mock.patch.object(od, "simple_chat", lambda **k: llm):
        return od._detect_offices(text)


class TestRule(unittest.TestCase):
    def test_parent_directly_in_front_of_its_child_is_dropped(self):
        self.assertEqual(detect("承辦單位：教務處註冊組"), ["註冊組"])

    def test_the_same_for_other_units(self):
        self.assertEqual(sorted(detect("請至總務處出納組繳費")), ["出納組"])

    def test_spaces_between_do_not_hide_the_pairing(self):
        self.assertEqual(detect("教務處 註冊組"), ["註冊組"])
        self.assertEqual(detect("教務處　註冊組"), ["註冊組"])

    def test_the_parent_alone_is_kept(self):
        self.assertEqual(detect("教務處的電話"), ["教務處"])

    def test_one_standalone_mention_is_enough_to_keep_the_parent(self):
        self.assertEqual(sorted(detect("教務處註冊組負責…，其他事項請洽教務處")), ["教務處", "註冊組"])

    def test_the_child_alone_is_kept(self):
        self.assertEqual(detect("註冊組"), ["註冊組"])

    def test_two_unrelated_names_are_both_kept(self):
        self.assertEqual(sorted(detect("註冊組與圖書館")), ["圖書館", "註冊組"])

    def test_a_name_the_llm_resolved_without_a_literal_match_is_never_dropped(self):
        # text says 教務處註冊組; the judge also answers 教務長室, which does not occur literally -> untouched
        self.assertEqual(sorted(detect("教務處註冊組", llm="教務長室")), ["教務長室", "註冊組"])

    def test_the_llm_naming_the_parent_too_does_not_bring_it_back(self):
        self.assertEqual(detect("教務處註冊組", llm="教務處,註冊組"), ["註冊組"])

    def test_nothing_in_the_text_nothing_returned(self):
        self.assertEqual(detect("今天天氣很好"), [])


@unittest.skipUnless(FIX.exists(), "fixtures not present")
class TestTheRealChain(unittest.TestCase):
    def test_the_xiuxue_page_and_forms_no_longer_yield_the_parent_but_keep_the_child(self):
        page = next(json.loads(l)["text"] for l in open(ROOT / "output" / "aca" / "extracted_texts.jsonl", encoding="utf-8")
                    if json.loads(l)["url"].endswith("休學-保留學籍-退學-提早復學") and "/zh/" in json.loads(l)["url"])
        text = "\n".join([page] + [(FIX / n).read_text(encoding="utf-8") for n in
                                   ("04_moltke_QP-T01-02-05.pdf.txt", "07_moltke_QP-T01-03-02.pdf.txt", "10_moltke_QP-T01-03-04.pdf.txt")])
        got = detect(text, catalog=od._keyword_table())
        self.assertIn("註冊組", got)
        self.assertNotIn("教務處", got)
        for kept in ("出納組", "國際合作事務處", "生活事務暨僑生輔導組", "身心健康中心"):
            self.assertIn(kept, got)


if __name__ == "__main__":
    unittest.main(verbosity=2)
