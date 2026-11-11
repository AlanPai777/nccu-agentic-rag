"""
規則版 Accuracy（evaluation/score_programmatic.py 的 accuracy）：用出納組的 gold 與手寫答案驗證。
K1 總機、K2 任一允許分機（只檢查分機值）、K3 條件式（答案列了「人名加分機」才適用，每一對都要相符）。
"""
import unittest

import helpers
from score_programmatic import accuracy, check_pairs


def verdicts(answer: str) -> dict:
    gold = helpers.read(helpers.GOLD)
    summary, per_kp = accuracy(gold, answer, [])
    return {k["id"]: k["verdict"] for k in per_kp}, summary, {k["id"]: k for k in per_kp}


class RuleAccuracyTest(unittest.TestCase):
    def test_switchboard_and_extension_without_any_person(self):
        v, s, _ = verdicts("電話 (02)2939-3091 分機 62120")
        self.assertEqual(v, {"K1": "hit", "K2": "hit", "K3": "not_applicable"})
        self.assertEqual((s["hit"], s["hard_keypoints"], s["accuracy"]), (2, 2, 1.0))     # 不適用的不計入

    def test_a_correct_person_pair_makes_k3_applicable_and_a_hit(self):
        v, s, _ = verdicts("電話 (02)2939-3091 分機 62120；劉桂芬（組長）分機 62120")
        self.assertEqual(v["K3"], "hit")
        self.assertEqual((s["hit"], s["hard_keypoints"]), (3, 3))

    def test_a_cross_paired_extension_makes_k3_wrong_and_leaves_k2_alone(self):
        v, s, k = verdicts("電話 (02)2939-3091 分機 62120；劉桂芬（組長）分機 62123")
        self.assertEqual(v, {"K1": "hit", "K2": "hit", "K3": "wrong"})      # 62123 在允許集合內，K2 不受連累
        self.assertEqual(k["K3"]["wrong"]["pair_mismatches"], [{"name": "劉桂芬", "said": "62123", "expected": "62120"}])
        self.assertEqual((s["hit"], s["hard_keypoints"]), (2, 3))

    def test_the_wrong_office_extension_is_a_wrong_value_not_a_hit(self):
        v, _, k = verdicts("出納組分機 62095。")
        self.assertEqual(v["K1"], "miss")
        self.assertEqual(v["K2"], "wrong")
        self.assertEqual(k["K2"]["wrong"]["disallowed"][0]["value"], "62095")

    def test_an_extension_outside_the_allowed_set_is_wrong_and_flagged_for_review(self):
        v, _, k = verdicts("電話 (02)2939-3091 分機 62120，另可撥 62999")
        self.assertEqual(v["K2"], "wrong")
        self.assertEqual(k["K2"]["wrong"]["unknown_values"], ["62999"])
        self.assertIn("needs_human_review", k["K2"])               # gold 可能漏了合法分機，要人看

    def test_an_answer_with_no_number_misses_everything_it_can_miss(self):
        v, s, _ = verdicts("請洽出納組辦理。")
        self.assertEqual(v, {"K1": "miss", "K2": "miss", "K3": "not_applicable"})
        self.assertEqual((s["hit"], s["hard_keypoints"], s["accuracy"]), (0, 2, 0.0))

    def test_an_allowed_extension_alone_hits_k2_but_not_k1(self):
        v, _, _ = verdicts("辦公室分機為 62123")
        self.assertEqual((v["K1"], v["K2"]), ("miss", "hit"))

    def test_the_pair_window_is_short_so_a_far_away_number_is_not_a_pair(self):
        gold = helpers.read(helpers.GOLD)
        people = gold["allowed_values"]["extension_by_person"]
        far = "劉桂芬是組長，" + "很多字" * 10 + "分機 62123"
        self.assertEqual(check_pairs(far, people), [])


if __name__ == "__main__":
    unittest.main()
