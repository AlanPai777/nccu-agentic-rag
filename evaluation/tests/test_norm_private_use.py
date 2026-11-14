"""比對用的 norm：忽略私用區字元（U+E000–U+F8FF，表單簽核欄的字型符號，肉眼看不到，不算內容）。

三個共用的 norm（gold_check、score_programmatic、registry_lib）規則要一致；stage3 借用 score_programmatic 的 norm。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "registry"))

import gold_check  # noqa: E402
import registry_lib  # noqa: E402
import score_programmatic  # noqa: E402
import stage3  # noqa: E402

# 表單 QP-T01-04-21 簽核流程表的原文：「單位主管」與「註冊組」之間夾著 U+F082（第 2 站的編號）
SOURCE = "| 承辦人 | 單位主管 |\n|  |  | 註冊組 | 承辦人 | 組 長 |"
QUOTE = "承辦人 | 單位主管 | 註冊組 | 承辦人 | 組 長"


class TestNormPrivateUse(unittest.TestCase):
    def test_all_three_norms_drop_private_use(self):
        for fn in (gold_check.norm, score_programmatic.norm, registry_lib.norm):
            self.assertEqual(fn("ABCD"), "ABCD", fn.__module__)

    def test_quote_across_private_use_character_is_found(self):
        for fn in (gold_check.norm, score_programmatic.norm):
            self.assertIn(fn(QUOTE), fn(SOURCE))

    def test_stage3_locate_finds_quote_across_private_use(self):
        self.assertIsNotNone(stage3._locate(SOURCE, QUOTE))

    def test_normal_text_is_unchanged(self):
        self.assertEqual(gold_check.norm("本校 學生：A|B"), "本校學生:AB")
        self.assertEqual(score_programmatic.norm("本校 學生：A|B"), "本校學生:AB")

    def test_a_missing_quote_is_still_missing(self):
        self.assertNotIn(score_programmatic.norm("承辦人 組長 註冊組"), score_programmatic.norm(SOURCE))


if __name__ == "__main__":
    unittest.main()
