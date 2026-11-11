"""
stage3 prepare：由 prediction.json 產生給判斷者的輸入。
trace_input.json 不含 gold；證據只有答案模型實際看到的內容，並剝掉系統加的來源行與標記行。
"""
import json
import tempfile
import unittest
from pathlib import Path

import helpers
from stage3 import build_evidence

MARKER = "[live:src status=snapshot kind=contact checked= snap=2026-08-25 tls=0 t=x url=https://cashier.nccu.edu.tw/PageStaffing?fid=7994]"


def ctx(**kw):
    base = {"message_index": 0, "role": "HumanMessage", "tool": None, "kind": None, "text": ""}
    base.update(kw)
    return base


class BuildEvidenceTest(unittest.TestCase):
    def test_contact_page_and_node_prompts_are_not_evidence(self):
        items, _ = build_evidence([
            ctx(kind="contact_list", text="出納組 分機 62120"),
            ctx(role="ContactPage", kind="contact_page", text="人員頁原文"),
            ctx(text="這一輪系統建議的搜尋方向：出納組 電話"),
            ctx(text="候選subdomain（依「出納組 電話」查詢得出）："),
            ctx(role="ToolMessage", tool="get_page", text="頁面內容"),
        ])
        self.assertEqual([i["kind"] for i in items], ["contact_list", "ToolMessage"])
        self.assertEqual([i["id"] for i in items], ["E1", "E2"])

    def test_marker_line_is_removed_and_its_url_kept_as_metadata(self):
        items, _ = build_evidence([ctx(kind="contact_list", text="出納組 分機 62120\n\n" + MARKER)])
        self.assertNotIn("live:src", items[0]["text"])
        self.assertEqual(items[0]["source_url"], "https://cashier.nccu.edu.tw/PageStaffing?fid=7994")

    def test_url_only_source_lines_are_stripped_and_reported(self):
        text = ("出納組 分機 62120\n    來源：https://cashier.nccu.edu.tw/PageStaffing?fid=7994\n"
                "    補充來源（樓層、電話）：https://osa.nccu.edu.tw/tw/休-退-學退費標準\n    • 劉桂芬（組長）分機 62120")
        items, removed = build_evidence([ctx(kind="contact_list", text=text)])
        self.assertEqual(len(removed), 2)
        self.assertNotIn("來源", items[0]["text"])
        self.assertNotIn("退費", items[0]["text"])                   # 網址路徑裡的字不再留在證據裡
        self.assertIn("劉桂芬（組長）分機 62120", items[0]["text"])

    def test_a_line_that_merely_starts_with_the_word_source_is_content_and_stays(self):
        text = "來源：教育部公告\n來源：https://x.edu.tw/a 的說明文字\n內文 [申請書](https://x.edu.tw/form)"
        items, removed = build_evidence([ctx(role="ToolMessage", tool="get_page", text=text)])
        self.assertEqual(removed, [])                                  # 整行都是網址才剝
        self.assertEqual(items[0]["text"], text)


class PrepareCliTest(unittest.TestCase):
    def test_prepare_writes_inputs_without_gold(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            helpers.write(d / "prediction.json", helpers.read(helpers.FIX / "cashier_clean_prediction.json"))
            r = helpers.cli("stage3.py", "prepare", helpers.GOLD, d)
            self.assertEqual(r.returncode, 0, r.stderr)
            t = helpers.read(d / "trace_input.json")
            blob = json.dumps(t, ensure_ascii=False)
            for gold_word in ("keypoint", "acceptable_expressions", "allowed_values", "references", "K1", "K2"):
                self.assertNotIn(gold_word, blob, gold_word)          # 回推看不到 gold
            self.assertEqual(len(t["evidence_items"]), 1)
            self.assertEqual(t["evidence_items"][0]["kind"], "contact_list")
            self.assertEqual(len(t["stripped_not_scored"]["evidence_source_lines"]), 3)
            self.assertEqual(len(t["stripped_not_scored"]["rationale"]), 2)
            self.assertNotIn("選擇原因", t["answer_text"])
            self.assertNotIn("**", t["answer_text"])

            j = helpers.read(d / "judge_input.json")
            self.assertEqual([k["id"] for k in j["keypoints"]], ["K1", "K2", "K3"])
            self.assertEqual(j["keypoints"][2]["applies_if"], "answer_names_contact_person")
            self.assertNotIn("references", json.dumps(j, ensure_ascii=False))     # 判斷也不給原文依據
            self.assertIn("承辦人與分機的正確配對（人員頁）", j["notes"])


if __name__ == "__main__":
    unittest.main()
