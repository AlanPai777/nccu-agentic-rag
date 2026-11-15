"""
gold 的 keypoint 標 `excluded` 的行為（議題 F39，2026-11-15，指標版本 2026-11-15.excluded-keypoints）。離線，不呼叫 LLM。

  * 沒有標 excluded 的題目：數字與以前逐位元相同，scores.json 多兩個空欄位
  * 標了的 keypoint 不進任何分母（Completeness、Hallucination、Irrelevance、Context Recall、規則版 Accuracy、Words／Sentence 字串比對）
  * 它的判定（judge.json）照舊保留，scores.json 的 excluded_keypoints 列出理由與當時的判定
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
GOLD = helpers.read(helpers.GOLD)
REASON = "測試：定義不夠明確，先不計分"


def run(gold: dict, judge=JUDGE):
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        gp = d / "gold.json"
        helpers.write(gp, gold)
        rd = d / "run"
        rd.mkdir()
        helpers.write(rd / "prediction.json", PRED)
        assert helpers.cli("stage3.py", "prepare", gp, rd).returncode == 0
        helpers.write(rd / "trace.json", TRACE)
        helpers.write(rd / "judge.json", judge)
        r = helpers.cli("score_programmatic.py", gp, rd / "prediction.json")
        assert r.returncode == 0, r.stderr
        r = helpers.cli("stage3.py", "score", gp, rd)
        assert r.returncode == 0, r.stdout + r.stderr
        s = helpers.read(rd / "scores.json")
        s["_stage2"] = helpers.read(rd / "scores.stage2.json")
        s["_stdout"] = r.stdout
        return s


def gold_excluding(*ids):
    g = copy.deepcopy(GOLD)
    for k in g["keypoints"]:
        if k["id"] in ids:
            k["excluded"] = {"reason": REASON, "since": "2026-11-15", "issue": "F39"}
    return g


class NoExclusionTest(unittest.TestCase):
    def test_a_gold_without_excluded_scores_as_before_with_empty_extra_fields(self):
        s = run(GOLD)
        self.assertEqual(s["excluded_keypoints"], [])
        self.assertEqual(s["keypoint"]["excluded"], 0)
        self.assertEqual(s["keypoint"]["total"], len(GOLD["keypoints"]))
        self.assertEqual(s["metrics_version"], "2026-11-15.excluded-keypoints")


class ExclusionTest(unittest.TestCase):
    def setUp(self):
        self.base = run(GOLD)
        self.s = run(gold_excluding("K1"))

    def test_the_excluded_keypoint_leaves_every_denominator(self):
        n = len(GOLD["keypoints"])
        self.assertEqual(self.s["keypoint"]["total"], n - 1)
        self.assertEqual(self.s["keypoint"]["excluded"], 1)
        self.assertEqual(self.s["keypoint"]["relevant"], self.base["keypoint"]["relevant"] - 1)      # K1 was relevant: no longer counted
        self.assertEqual(self.s["context"]["sentence"]["applicable"], n - 1)
        self.assertEqual(self.s["context"]["sentence"]["read"], self.base["context"]["sentence"]["read"] - 1)
        self.assertEqual(self.s["keypoint"]["completeness"], 1.0)

    def test_it_is_listed_with_the_reason_and_the_judgement_that_was_kept(self):
        (e,) = self.s["excluded_keypoints"]
        self.assertEqual((e["id"], e["reason"], e["issue"], e["judged"]), ("K1", REASON, "F39", "relevant"))
        f = {x["id"]: x for x in self.s["funnel"]}["K1"]
        self.assertEqual((f["verdict"], f["in_context"], f["in_context_source"], f["excluded_reason"]), ("excluded", None, "excluded", REASON))
        self.assertIn("不計分", self.s["_stdout"])

    def test_a_wrong_verdict_on_an_excluded_keypoint_is_not_a_hallucination(self):
        j = copy.deepcopy(JUDGE)
        j["keypoints"][0].update({"verdict": "wrong", "reason": "測試", "in_context": True, "context_quote": PRED["context"][1]["text"][:30]})
        s = run(gold_excluding("K1"), j)
        self.assertEqual(s["keypoint"]["wrong"], 0)
        self.assertEqual(s["keypoint"]["hallucination"], 0.0)
        self.assertEqual(s["excluded_keypoints"][0]["judged"], "wrong")
        # the same judgement without the flag does count
        self.assertGreater(run(GOLD, j)["keypoint"]["hallucination"], 0)

    def test_the_rule_accuracy_and_the_string_match_leave_it_out_too(self):
        k1 = next(k for k in GOLD["keypoints"] if k["id"] == "K1")
        hard_before = self.base["_stage2"]["accuracy"]["hard_keypoints"]
        hard_after = self.s["_stage2"]["accuracy"]["hard_keypoints"]
        self.assertEqual(hard_after, hard_before - (1 if k1.get("kind", "hard") == "hard" else 0))
        rows = {r["id"]: r for r in self.s["_stage2"]["keypoints"]["accuracy_rule"]}
        self.assertEqual(rows["K1"]["verdict"], "excluded")
        sm = {r["id"]: r for r in self.s["_stage2"]["context"]["string_match"]}
        self.assertIsNone(sm["K1"]["found"])

    def test_other_keypoints_are_not_touched(self):
        for kid in ("K2", "K3"):
            a = {f["id"]: f for f in self.base["funnel"]}[kid]
            b = {f["id"]: f for f in self.s["funnel"]}[kid]
            self.assertEqual(a, b)


class RealGoldTest(unittest.TestCase):
    def test_q7_marks_only_k10_and_k11_and_only_adds_the_flag(self):
        g = helpers.read(helpers.EVAL / "master_transfer" / "gold.json")
        marked = {k["id"]: k["excluded"] for k in g["keypoints"] if k.get("excluded")}
        self.assertEqual(sorted(marked), ["K10", "K11"])
        for e in marked.values():
            self.assertEqual((e["issue"], e["since"]), ("F39", "2026-11-15"))
            self.assertTrue(e["reason"])
        others = [k for k in g["keypoints"] if k["id"] not in marked]
        self.assertTrue(others and all("excluded" not in k for k in others))
        self.assertEqual(len(g["keypoints"]), 29)

    def test_no_other_question_has_an_excluded_keypoint(self):
        for gp in sorted(helpers.EVAL.glob("*/gold.json")):
            if gp.parent.name == "master_transfer":
                continue
            g = helpers.read(gp)
            self.assertFalse([k["id"] for k in g["keypoints"] if k.get("excluded")], gp.parent.name)


if __name__ == "__main__":
    unittest.main()
