"""
split_answer（evaluation/run_system.py）：評分前把答案剝成「正文」。
剝掉【資料狀態】、答案最後的「來源：」行、每位承辦人後面的「——選擇原因：…」，並把剝掉的文字另存。
"""
import unittest

import helpers
from run_system import split_answer


class SplitAnswerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = helpers.read(helpers.FIX / "cashier_clean_prediction.json")["answer_raw"]

    def test_real_answer_is_cut_into_body_and_stripped_parts(self):
        body, stripped = split_answer(self.raw)
        self.assertNotIn("選擇原因", body)
        self.assertNotIn("來源：", body)
        self.assertNotIn("【資料狀態】", body)
        self.assertIn("劉桂芬（組長）分機 62120", body)          # 事實留著，只剝掉理由
        self.assertEqual(len(stripped["rationale"]), 2)
        self.assertTrue(stripped["rationale"][0].startswith("——選擇原因："))
        self.assertTrue(stripped["sources"].startswith("來源："))
        self.assertTrue(stripped["disclosure"].startswith("【資料狀態】"))

    def test_other_dash_and_colon_forms_of_the_rationale_are_stripped(self):
        for text in ("劉桂芬 分機 62120—選擇原因：主管", "劉桂芬 分機 62120 -- 選擇原因:主管", "劉桂芬 分機 62120 – 選擇原因：主管"):
            body, stripped = split_answer(text)
            self.assertEqual(body, "劉桂芬 分機 62120", text)
            self.assertEqual(len(stripped["rationale"]), 1)

    def test_no_rationale_leaves_the_body_alone(self):
        body, stripped = split_answer("出納組分機 62120。")
        self.assertEqual(body, "出納組分機 62120。")
        self.assertEqual(stripped["rationale"], [])

    def test_the_word_source_inside_a_sentence_is_not_cut(self):
        text = "資料來源於官網的說明如下：分機 62120。"
        body, stripped = split_answer(text)
        self.assertEqual(body, text)
        self.assertEqual(stripped["sources"], "")

    def test_a_source_line_with_something_other_than_urls_after_it_is_kept(self):
        text = "分機 62120。\n來源：請洽出納組櫃台"
        body, stripped = split_answer(text)
        self.assertIn("來源：請洽出納組櫃台", body)             # 後面不是網址，不能當成來源行剝掉


if __name__ == "__main__":
    unittest.main()
