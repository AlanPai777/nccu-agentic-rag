"""
run 的管理（離線，不呼叫 LLM）：run_system.new_run_id 的取號規則、list_runs 的列表與結束碼。
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import helpers

sys.path.insert(0, str(helpers.ROOT / "evaluation"))
import list_runs  # noqa: E402
import run_system  # noqa: E402

LIST_RUNS = helpers.ROOT / "evaluation" / "list_runs.py"


def tmpdir(test) -> Path:
    d = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, d, True)
    return d


def make_run(runs: Path, name: str, **pred):
    d = runs / name
    d.mkdir(parents=True)
    helpers.write(d / "prediction.json", dict({"run_id": name, "label": "", "started_at": "2026-11-11T10:00:00+08:00",
                                               "model": "m", "system_version": "abc"}, **pred))
    return d


class NewRunIdTest(unittest.TestCase):
    def test_empty_folder_starts_at_run01(self):
        self.assertEqual(run_system.new_run_id(tmpdir(self)), "run01")

    def test_next_is_max_plus_one_not_the_count(self):
        runs = tmpdir(self)
        for n in ("run01", "run03"):          # run02 被刪掉了
            (runs / n).mkdir()
        self.assertEqual(run_system.new_run_id(runs), "run04")

    def test_other_names_and_plain_files_are_ignored(self):
        runs = tmpdir(self)
        (runs / "20261109-212602").mkdir()
        (runs / "run07").write_text("a file, not a run", encoding="utf-8")
        (runs / "run2x").mkdir()
        self.assertEqual(run_system.new_run_id(runs), "run01")

    def test_numbers_past_99_still_sort_by_value(self):
        runs = tmpdir(self)
        (runs / "run99").mkdir()
        self.assertEqual(run_system.new_run_id(runs), "run100")


class ListRunsTest(unittest.TestCase):
    def test_a_scored_run_shows_label_and_numbers(self):
        runs = tmpdir(self) / "runs"
        d = make_run(runs, "run01", label="修正前，試做")
        helpers.write(d / "scores.stage2.json", {})
        helpers.write(d / "scores.json", {"keypoint": {"completeness": 0.67}, "evidence_support": {"rate": 0.45}})
        rows = list_runs.collect(runs)
        self.assertEqual(rows[0]["label"], "修正前，試做")
        self.assertTrue(rows[0]["stage2"] and rows[0]["stage3"])
        self.assertEqual((rows[0]["completeness"], rows[0]["support_rate"]), (0.67, 0.45))
        text = list_runs.render(rows)
        self.assertIn("0.67", text)
        self.assertIn("修正前，試做", text)

    def test_a_run_without_scores_shows_dashes(self):
        runs = tmpdir(self) / "runs"
        make_run(runs, "run01")
        row = list_runs.collect(runs)[0]
        self.assertFalse(row["stage3"])
        self.assertIsNone(row["completeness"])

    def test_a_folder_without_prediction_is_skipped_and_a_mismatch_is_flagged(self):
        runs = tmpdir(self) / "runs"
        (runs / "empty").mkdir(parents=True)
        make_run(runs, "run02", run_id="run99")
        rows = list_runs.collect(runs)
        self.assertEqual([r["folder"] for r in rows], ["run02"])
        self.assertFalse(rows[0]["id_matches_folder"])
        self.assertIn("run_id 與資料夾名不同", list_runs.render(rows))

    def test_cli_accepts_the_question_folder_or_runs_and_exits_2_when_empty(self):
        q = tmpdir(self)
        make_run(q / "runs", "run01")
        for arg in (q, q / "runs"):
            r = subprocess.run([sys.executable, str(LIST_RUNS), str(arg), "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)[0]["folder"], "run01")
        e = tmpdir(self)
        (e / "runs").mkdir()
        self.assertEqual(subprocess.run([sys.executable, str(LIST_RUNS), str(e)], capture_output=True, text=True).returncode, 2)
        self.assertEqual(subprocess.run([sys.executable, str(LIST_RUNS), str(e / "nope")], capture_output=True, text=True).returncode, 2)

    def test_the_real_cashier_runs_are_listed(self):
        rows = list_runs.collect(helpers.GOLD.parent / "runs")
        self.assertIn("run01", [r["folder"] for r in rows])


if __name__ == "__main__":
    unittest.main()
