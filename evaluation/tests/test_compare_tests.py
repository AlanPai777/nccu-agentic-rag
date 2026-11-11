"""
compare_tests.py：盲回推結果與預期鑰匙的比對（tampered_v1 的記錄）。
子代理每次輸出不同，所以這裡只用「記錄下來的那一次」當固定資料，測比對邏輯本身；不是斷言子代理一定抓得到。
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
from compare_tests import compare


class CompareRecordedRunTest(unittest.TestCase):
    def test_recorded_run1_catches_every_planted_error_and_keeps_the_controls(self):
        r = compare(helpers.TAMPER, "run1")
        self.assertEqual((r["caught"], r["planted"]), (6, 6))
        self.assertEqual((r["controls_ok"], r["controls"]), (3, 3))
        self.assertEqual(r["failed"], [])
        self.assertEqual(r["review"], [])
        self.assertEqual(r["claims_total"], 14)
        self.assertEqual(r["claims_counted"], 11)                  # 被包含的 c7、c9、c11 不計入
        by_id = {x["id"]: x for x in r["rows"]}
        self.assertEqual(by_id["T6"]["claims"], [("c7", "supported"), ("c8", "unsupported")])    # 交叉配對：整句被標出
        self.assertEqual(by_id["T9"]["claims"], [("c13", "unsupported"), ("c14", "supported")])  # 職稱被改：職稱被標出

    def _copy_with_trace(self, edit):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        shutil.copy(helpers.TAMPER / "expected.json", d / "expected.json")
        shutil.copy(helpers.TAMPER / "trace_input.json", d / "trace_input.json")
        (d / "results" / "run1").mkdir(parents=True)
        tr = helpers.read(helpers.TAMPER / "results" / "run1" / "trace.json")
        edit(tr)
        helpers.write(d / "results" / "run1" / "trace.json", tr)
        return d

    def test_a_missed_error_is_a_failure_and_the_cli_exits_1(self):
        def edit(tr):
            for c in tr["claims"]:
                if c["id"] == "c3":                                # 傳真 4785：把它誤判成 supported
                    c["status"] = "supported"
                    c["evidence"] = [{"item": "E1", "quote": "傳真 (02)2939-4784"}]
        d = self._copy_with_trace(edit)
        r = compare(d)
        self.assertEqual(r["failed"], ["T2"])
        self.assertEqual(r["caught"], 5)
        p = helpers.cli("compare_tests.py", d)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)

    def test_a_control_flagged_unsupported_is_a_failure(self):
        def edit(tr):
            for c in tr["claims"]:
                if c["id"] == "c10":                               # 余淑娟是對照組：誤判成 unsupported
                    c["status"], c["evidence"] = "unsupported", []
        r = compare(self._copy_with_trace(edit))
        self.assertEqual(r["failed"], ["T7"])
        self.assertEqual(r["controls_ok"], 2)

    def test_an_ambiguous_item_that_differs_is_review_not_failure(self):
        def edit(tr):
            for c in tr["claims"]:
                if c["id"] == "c6":                                # 退費職掌（T5，ambiguous）被判 supported
                    c["status"] = "supported"
                    c["evidence"] = [{"item": "E1", "quote": "補充來源（樓層、電話）"}]
        d = self._copy_with_trace(edit)
        r = compare(d)
        self.assertEqual(r["review"], ["T5"])
        self.assertEqual(r["failed"], [])
        self.assertEqual(helpers.cli("compare_tests.py", d).returncode, 0)

    def test_an_uncovered_line_is_a_failure(self):
        def edit(tr):
            tr["claims"] = [c for c in tr["claims"] if c["id"] != "c5"]    # 辦公時間那一行完全沒有主張
        r = compare(self._copy_with_trace(edit))
        self.assertEqual(r["failed"], ["T4"])

    def test_cli_on_the_recorded_run_exits_0_and_missing_files_exit_2(self):
        self.assertEqual(helpers.cli("compare_tests.py", helpers.TAMPER).returncode, 0)
        self.assertEqual(helpers.cli("compare_tests.py", helpers.TAMPER, "--run", "nope").returncode, 2)
        p = helpers.cli("compare_tests.py", helpers.TAMPER, "--json")
        self.assertEqual(json.loads(p.stdout)["caught"], 6)


if __name__ == "__main__":
    unittest.main()
