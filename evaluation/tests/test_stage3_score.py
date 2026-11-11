"""
stage3 score 與 score_programmatic：整條離線管線在三個出納組案例上的預期數字（定義凍結檢查）。

  乾淨答案      列了兩位承辦人，配對都對，6 個主張全有依據
  改壞的答案    劉桂芬配 62123、林瓊蓮職稱錯、傳真與樓層錯、憑空的辦公時間與職掌；盲回推用 tampered_v1 的記錄
  沒列承辦人    K3 不適用，不計入分母

這些數字是 2026-11-11 與使用者確認的定義（plan/phase_k_evaluation_design.md 第 13 節）。
若這裡的斷言失敗，代表有人改了指標的算法：那是定義變更，要註明版本，舊分數不能與新分數直接比較。
"""
import tempfile
import unittest
from pathlib import Path

import helpers

PRED = helpers.read(helpers.FIX / "cashier_clean_prediction.json")


def approx(test, value, expected, places=3):
    test.assertIsNotNone(value)
    test.assertAlmostEqual(value, expected, places=places)


class CleanAnswerTest(unittest.TestCase):
    def test_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            helpers.build_run(d, prediction=PRED, trace=helpers.read(helpers.FIX / "cashier_clean_trace.json"),
                              judge=helpers.read(helpers.FIX / "cashier_clean_judge.json"), prepare=True)
            s = helpers.score(d)
        kp = s["keypoint"]
        self.assertEqual((kp["relevant"], kp["wrong"], kp["irrelevant"], kp["not_applicable"], kp["total"]), (3, 0, 0, 0, 3))
        self.assertEqual((kp["completeness"], kp["hallucination"], kp["irrelevance"]), (1.0, 0.0, 0.0))
        self.assertEqual((s["fact_unit"]["precision"], s["fact_unit"]["recall"], s["fact_unit"]["f1"]), (1.0, 1.0, 1.0))
        approx(self, s["claim_unit"]["precision"], 4 / 6)          # 6 個主張裡 4 個直接陳述 keypoint，傳真與樓層是額外的正確資訊
        self.assertEqual(s["claim_unit"]["recall"], 1.0)
        approx(self, s["claim_unit"]["f1"], 0.8)
        self.assertEqual((s["evidence_support"]["supported"], s["evidence_support"]["claims"], s["evidence_support"]["rate"]), (6, 6, 1.0))
        self.assertEqual(s["accuracy_rule"]["hit"], 3)
        self.assertEqual(s["disagreements"], [])
        self.assertEqual(s["ungrounded_correct_keypoints"], [])
        self.assertEqual(s["context"]["sentence"]["r"], 1.0)


class TamperedAnswerTest(unittest.TestCase):
    def test_numbers(self):
        tampered = (helpers.TAMPER / "answer.txt").read_text(encoding="utf-8").rstrip("\n")
        pred = dict(PRED, answer_raw=tampered, answer_body=tampered, run_id="tamper")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            helpers.build_run(d, prediction=pred, trace_input=helpers.read(helpers.TAMPER / "trace_input.json"),
                              trace=helpers.read(helpers.TAMPER / "results" / "run1" / "trace.json"),
                              judge=helpers.read(helpers.FIX / "cashier_tamper_judge.json"))
            s = helpers.score(d)
        kp = s["keypoint"]
        self.assertEqual((kp["relevant"], kp["wrong"], kp["total"]), (2, 1, 3))
        approx(self, kp["completeness"], 2 / 3)
        approx(self, kp["hallucination"], 1 / 3)
        for k in ("precision", "recall", "f1"):
            approx(self, s["fact_unit"][k], 2 / 3)
        # 14 個主張，c7、c9、c11 被較長的主張包含不計入 → 11 個；正確陳述 keypoint 的主張 c1、c2、c10、c12、c14
        self.assertEqual((s["claim_unit"]["claims"], s["claim_unit"]["correct_claims"]), (11, 5))
        approx(self, s["claim_unit"]["precision"], 5 / 11)
        approx(self, s["claim_unit"]["recall"], 2 / 3)
        approx(self, s["claim_unit"]["f1"], 0.5405)
        ev = s["evidence_support"]
        self.assertEqual((ev["supported"], ev["claims"]), (5, 11))
        approx(self, ev["rate"], 5 / 11)
        self.assertEqual(ev["unsupported_claims"], ["c3", "c4", "c5", "c6", "c8", "c13"])
        self.assertEqual(s["accuracy_rule"]["hit"], 2)
        self.assertEqual(s["accuracy_rule"]["hard_keypoints"], 3)
        self.assertEqual(s["disagreements"], [])                    # 規則版與判斷都說 K3 wrong
        self.assertEqual(sum("包含" in w for w in s["warnings"]), 3)


class NoPersonAnswerTest(unittest.TestCase):
    def test_k3_is_not_applicable_and_left_out_of_the_denominators(self):
        text = "總務處出納組的聯絡資訊如下：\n\n*   電話： (02) 2939-3091 分機 62120\n*   傳真： (02) 2939-4784\n*   地點： 行政大樓 5 樓"
        ev = lambda q: [{"item": "E1", "quote": q}]
        trace = {"claims": [
            {"id": "c1", "answer_span": "(02) 2939-3091", "status": "supported", "evidence": ev("電話 (02)2939-3091 分機 62120")},
            {"id": "c2", "answer_span": "分機 62120", "status": "supported", "evidence": ev("電話 (02)2939-3091 分機 62120")},
            {"id": "c3", "answer_span": "(02) 2939-4784", "status": "supported", "evidence": ev("傳真 (02)2939-4784")},
            {"id": "c4", "answer_span": "行政大樓 5 樓", "status": "supported", "evidence": ev("行政大樓 5 樓")}],
            "judge": {"model": "test"}}
        judge = {"keypoints": [{"id": "K1", "verdict": "relevant", "claims": ["c1"]}, {"id": "K2", "verdict": "relevant", "claims": ["c2"]},
                               {"id": "K3", "verdict": "not_applicable", "claims": []}], "judge": {"model": "test"}}
        ti = dict(helpers.read(helpers.TAMPER / "trace_input.json"), answer_text=text)
        pred = dict(PRED, answer_raw=text, answer_body=text, run_id="nopeople")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            helpers.build_run(d, prediction=pred, trace_input=ti, trace=trace, judge=judge)
            s = helpers.score(d)
        kp = s["keypoint"]
        self.assertEqual((kp["relevant"], kp["not_applicable"], kp["total"]), (2, 1, 2))
        self.assertEqual(kp["completeness"], 1.0)
        self.assertEqual(s["fact_unit"]["f1"], 1.0)
        approx(self, s["claim_unit"]["precision"], 0.5)             # 4 個主張裡 2 個直接陳述 keypoint
        approx(self, s["claim_unit"]["f1"], 2 / 3)
        self.assertEqual((s["accuracy_rule"]["hit"], s["accuracy_rule"]["hard_keypoints"]), (2, 2))
        self.assertEqual(s["disagreements"], [])
        self.assertEqual([f["verdict"] for f in s["funnel"]], ["relevant", "relevant", "not_applicable"])


class DisagreementTest(unittest.TestCase):
    def test_rule_hit_but_judge_wrong_is_listed(self):
        judge = helpers.read(helpers.FIX / "cashier_clean_judge.json")
        judge["keypoints"][1]["verdict"] = "wrong"                  # 規則版 K2 是 hit，故意讓判斷者判 wrong
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            helpers.build_run(d, prediction=PRED, trace=helpers.read(helpers.FIX / "cashier_clean_trace.json"), judge=judge, prepare=True)
            s = helpers.score(d)
        self.assertEqual([x["keypoint"] for x in s["disagreements"]], ["K2"])
        self.assertEqual((s["disagreements"][0]["rule"], s["disagreements"][0]["claude"]), ("hit", "wrong"))

    def test_a_missing_keypoint_in_the_judgement_is_a_warning_and_counts_as_irrelevant(self):
        judge = helpers.read(helpers.FIX / "cashier_clean_judge.json")
        judge["keypoints"] = judge["keypoints"][:2]                 # 缺 K3
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            helpers.build_run(d, prediction=PRED, trace=helpers.read(helpers.FIX / "cashier_clean_trace.json"), judge=judge, prepare=True)
            s = helpers.score(d)
        self.assertTrue(any("缺少 K3" in w for w in s["warnings"]))
        self.assertEqual(s["keypoint"]["irrelevant"], 1)


if __name__ == "__main__":
    unittest.main()
