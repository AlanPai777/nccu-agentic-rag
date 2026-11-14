"""evaluation/reference_answer.py 與 gold_check.check_reference_answer：標記解析與建置檢查。離線。"""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import gold_check  # noqa: E402
import reference_answer  # noqa: E402


class TestParse(unittest.TestCase):
    def test_all_marker_kinds(self):
        segs = reference_answer.parse("A {{固定|X}} B {{可替換:K2|劉桂芬 62120}} C{{選答}}")
        self.assertEqual([(s["t"], s["v"]) for s in segs],
                         [("text", "A "), ("fixed", "X"), ("text", " B "), ("rep", "劉桂芬 62120"), ("text", " C"), ("opt", "（選答）")])
        self.assertEqual(segs[3]["kp"], "K2")

    def test_plain_text_and_formatting_pass_through(self):
        t = "**規定**\n*   第一\n1. 第二"
        self.assertEqual(reference_answer.parse(t), [{"t": "text", "v": t}])

    def test_bad_markers_raise(self):
        for bad in ("{{固定|abc", "x }} y", "{{固定}}", "{{可替換:K1}}", "{{不明|x}}"):
            with self.assertRaises(ValueError, msg=bad):
                reference_answer.parse(bad)


class TestCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gold = json.loads((HERE.parent / "cashier_contact" / "gold.json").read_text(encoding="utf-8"))
        cls.reg = gold_check.registry_lib.load()

    def check(self, text):
        """標記檢查的問題（短文字會漏 hard keypoint，涵蓋檢查另外測）。"""
        return [p for p in gold_check.check_reference_answer(dict(self.gold, reference_answer=text), self.reg) if "漏了 hard" not in p]

    def test_the_real_cashier_answer_passes(self):
        self.assertEqual(gold_check.check_reference_answer(self.gold, self.reg), [])

    def test_no_reference_answer_is_fine(self):
        self.assertEqual(gold_check.check_reference_answer({"keypoints": []}, None), [])

    def test_fixed_phrase_needs_a_basis(self):
        self.assertTrue(self.check("{{固定|(02) 1111-2222}}"))
        self.assertEqual(self.check("{{固定|(02) 2939-3091}}"), [])

    def test_replaceable_name_must_match_the_extension(self):
        self.assertEqual(self.check("{{可替換:K2|余淑娟（一級行政組員）分機 62123}}"), [])
        self.assertTrue(self.check("{{可替換:K2|余淑娟（組員）分機 62120}}"))        # 姓名與分機配錯
        self.assertTrue(self.check("{{可替換:K2|分機 99999}}"))                      # 分機不在允許集合
        self.assertTrue(self.check("{{可替換:K2|劉桂芬}}"))                          # 沒有分機
        self.assertTrue(self.check("{{可替換:K1|62120}}"))                           # K1 不是人員或分機型

    def test_a_number_without_a_person_is_allowed_for_extensions(self):
        self.assertEqual(self.check("{{可替換:K2|分機 62119}}"), [])                  # 通知單列的線路，沒有人名


class TestAllQuestions(unittest.TestCase):
    """11 題都有 reference_answer，而且全部通過建置檢查（標記合法、不可替換有依據、人員與分機配得上、hard keypoint 沒漏）。"""

    def test_every_gold_has_a_checked_reference_answer(self):
        reg = gold_check.registry_lib.load()
        golds = sorted(HERE.parent.glob("*/gold.json"))
        self.assertEqual(len(golds), 11)
        for path in golds:
            gold = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(gold.get("reference_answer"), f"{path.parent.name} 沒有 reference_answer")
            self.assertEqual(gold_check.check_reference_answer(gold, reg), [], path.parent.name)

    def test_a_missing_hard_value_is_caught(self):
        gold = json.loads((HERE.parent / "resumption" / "gold.json").read_text(encoding="utf-8"))
        text = gold["reference_answer"].replace("viewdetail=QP-T01-03-04", "viewdetail=X")      # 連結改掉，K4（下載連結）就漏了
        problems = gold_check.check_reference_answer(dict(gold, reference_answer=text), gold_check.registry_lib.load())
        self.assertTrue(any("漏了 hard keypoint" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
