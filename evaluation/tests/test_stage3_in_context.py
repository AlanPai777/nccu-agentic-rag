"""
「系統有沒有讀到」（in_context）改由 Claude 判斷之後的行為（2026-11-15，plan 13.19）。離線，不呼叫 LLM。

  * 答對而且有依據的 keypoint → 直接算讀到（inferred）；不適用的不判
  * 沒答對的 keypoint → 看 judge.json 的 in_context；true 一定要附引文，引文要真的在系統讀到的文字裡；沒有判斷 → 警告、算沒讀到
  * Context Sentence Recall = 讀到的 ÷ 適用的 keypoint（含引用登記表的）；Precision 仍是字串比對；F1 混合
  * in_context 無論怎麼判，Completeness、Hallucination、Irrelevance、事實／答案為單位、Accuracy 都不能變
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

import helpers

PRED = helpers.read(helpers.FIX / "cashier_clean_prediction.json")
TRACE = helpers.read(helpers.FIX / "cashier_clean_trace.json")
JUDGE = helpers.read(helpers.FIX / "cashier_clean_judge.json")
SCALAR_KEYS = ("keypoint", "fact_unit", "claim_unit", "evidence_support", "accuracy_rule", "rouge_l")


def run_score(judge, prediction=PRED):
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        helpers.build_run(d, prediction=prediction, trace=TRACE, judge=judge, prepare=True)
        s = helpers.score(d)
        s["_stage2"] = helpers.read(d / "scores.stage2.json")
        s["_judge_input"] = helpers.read(d / "judge_input.json")
        return s


def judge_with(k1):
    """K1 沒答對（irrelevant、沒有主張），K2、K3 照舊答對有依據。k1 是要加到 K1 的 in_context 欄位。"""
    j = copy.deepcopy(JUDGE)
    j["keypoints"][0].update({"verdict": "irrelevant", "claims": [], "reason": "答案沒寫總機"}, **k1)
    return j


def funnel(s):
    return {f["id"]: f for f in s["funnel"]}


class InferredTest(unittest.TestCase):
    def test_correct_and_grounded_keypoints_count_as_read_without_any_judgement(self):
        s = run_score(JUDGE)
        self.assertEqual([(f["in_context"], f["in_context_source"]) for f in s["funnel"]], [(True, "inferred")] * 3)
        self.assertEqual(s["context"]["sentence"]["r"], 1.0)
        self.assertEqual((s["context"]["sentence"]["read"], s["context"]["sentence"]["applicable"]), (3, 3))

    def test_the_old_string_match_is_gone_from_stage_2(self):
        s2 = run_score(JUDGE)["_stage2"]
        self.assertIsNone(s2["context"]["sentence"]["r"])
        self.assertIsNone(s2["context"]["sentence"]["f"])
        self.assertIn("p", s2["context"]["sentence"])                       # 字串比對的 Precision 還在
        self.assertNotIn("contact_funnel", s2["keypoints"])
        for row in s2["keypoints"]["funnel_stage2"]:
            self.assertNotIn("in_context", row)
            self.assertNotIn("matched_reference", row)
        self.assertEqual(s2["metrics_version"], "2026-11-15.context-recall-judged")


class JudgedTest(unittest.TestCase):
    def test_a_judged_true_with_a_real_quote_counts(self):
        quote = PRED["context"][1]["text"][:30]                              # 系統讀到的人員頁開頭，原樣
        s = run_score(judge_with({"in_context": True, "context_quote": quote, "context_reason": "頁面有"}))
        f = funnel(s)["K1"]
        self.assertEqual((f["in_context"], f["in_context_source"], f["context_quote"]), (True, "claude", quote))
        self.assertEqual(s["context"]["sentence"]["r"], 1.0)
        self.assertEqual(s["warnings"], [w for w in s["warnings"] if "in_context" not in w])

    def test_a_judged_false_does_not_count_and_needs_no_quote(self):
        s = run_score(judge_with({"in_context": False, "context_reason": "頁面沒有總機"}))
        f = funnel(s)["K1"]
        self.assertEqual((f["in_context"], f["in_context_source"]), (False, "claude"))
        self.assertAlmostEqual(s["context"]["sentence"]["r"], 2 / 3, places=4)

    def test_a_true_with_a_quote_not_in_what_the_system_read_is_not_believed(self):
        s = run_score(judge_with({"in_context": True, "context_quote": "這句話根本不在系統讀到的文字裡", "context_reason": "x"}))
        self.assertEqual((funnel(s)["K1"]["in_context"], funnel(s)["K1"]["in_context_source"]), (False, "claude-unverified"))
        self.assertTrue(any("context_quote" in w for w in s["warnings"]))

    def test_a_true_without_a_quote_is_not_believed(self):
        s = run_score(judge_with({"in_context": True, "context_reason": "x"}))
        self.assertEqual(funnel(s)["K1"]["in_context_source"], "claude-unverified")

    def test_a_missing_judgement_is_a_warning_and_counts_as_not_read(self):
        s = run_score(judge_with({}))
        self.assertEqual((funnel(s)["K1"]["in_context"], funnel(s)["K1"]["in_context_source"]), (False, "missing"))
        self.assertTrue(any("K1" in w and "in_context" in w for w in s["warnings"]))

    def test_the_quote_may_come_from_the_contact_list_the_answer_model_saw(self):
        quote = PRED["context"][0]["text"].split("\n")[3][:20]
        s = run_score(judge_with({"in_context": True, "context_quote": quote, "context_reason": "清單有"}))
        self.assertEqual(funnel(s)["K1"]["in_context_source"], "claude")


class NotApplicableTest(unittest.TestCase):
    def test_a_not_applicable_keypoint_is_left_out_of_the_denominator(self):
        j = copy.deepcopy(JUDGE)
        j["keypoints"][2].update({"verdict": "not_applicable", "claims": []})
        s = run_score(j)
        self.assertEqual(funnel(s)["K3"]["in_context"], None)
        self.assertEqual((s["context"]["sentence"]["read"], s["context"]["sentence"]["applicable"], s["context"]["sentence"]["r"]), (2, 2, 1.0))


class NothingElseMovesTest(unittest.TestCase):
    def test_in_context_never_changes_the_keypoint_scores(self):
        a = run_score(judge_with({"in_context": False, "context_reason": "沒有"}))
        b = run_score(judge_with({"in_context": True, "context_quote": PRED["context"][1]["text"][:30], "context_reason": "有"}))
        c = run_score(judge_with({}))
        for key in SCALAR_KEYS:
            self.assertEqual(a[key], b[key], key)
            self.assertEqual(a[key], c[key], key)
        self.assertNotEqual(a["context"]["sentence"]["r"], b["context"]["sentence"]["r"])      # 只有 Context 的 Recall 不同


class LabelsTest(unittest.TestCase):
    def test_the_context_block_says_where_each_number_comes_from(self):
        s = run_score(JUDGE)
        sen = s["context"]["sentence"]
        self.assertIn("Claude", sen["r_source"])
        self.assertIn("字串比對", sen["p_source"])
        self.assertIn("混合", sen["f_note"])
        self.assertEqual(s["metrics_version"], "2026-11-15.context-recall-judged")
        self.assertIn("不能與之後的直接比較", s["context"]["metrics_note"])
        self.assertIsNotNone(sen["f"])


class JudgeInputTest(unittest.TestCase):
    def test_judge_input_lists_what_the_system_read_and_the_in_context_rules(self):
        ji = run_score(JUDGE)["_judge_input"]
        kinds = [(it["kind"], it["role"]) for it in ji["context_items"]]
        self.assertIn(("contact_page", "ContactPage"), kinds)
        self.assertIn(("contact_list", "HumanMessage"), kinds)
        self.assertTrue(all("text" not in it for it in ji["context_items"]))                  # 只列長度與標題，全文在 prediction.json
        rules = " ".join(ji["output_format"]["rules"])
        self.assertIn("in_context", rules)
        self.assertIn("context_quote", rules)
        self.assertIn("prediction.json", ji["context_note"])


class CheckQuotesTest(unittest.TestCase):
    def test_check_reports_quotes_that_are_not_in_what_the_system_read(self):
        import stage3
        j = judge_with({"in_context": True, "context_quote": "不存在的一句話", "context_reason": "x"})
        self.assertEqual(stage3.check_in_context_quotes(j, PRED), ["K1"])
        good = judge_with({"in_context": True, "context_quote": PRED["context"][1]["text"][:30], "context_reason": "x"})
        self.assertEqual(stage3.check_in_context_quotes(good, PRED), [])


if __name__ == "__main__":
    unittest.main()
