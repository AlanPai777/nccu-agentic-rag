"""
.claude/skills/ 底下三個評測 skill 的薄腳本（離線，不呼叫 LLM）：
  run-eval-question/scripts/prepare_isolated_dir.py   隔離回推的空資料夾：只放 trace_input.json，含 gold 字眼或資料夾非空就拒絕
  run-eval-question/scripts/verify_run.py          算分前的檔案與格式關卡
  build-eval-gold/scripts/verify_gold.py           gold 的驗證關卡
  isolated-trace-check/scripts/make_tampered_version.py   由既有版本建立改壞答案測試的新版本
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import helpers

SKILLS = helpers.ROOT / ".claude" / "skills"
ISOLATED = SKILLS / "run-eval-question" / "scripts" / "prepare_isolated_dir.py"
AUDIT = SKILLS / "run-eval-question" / "scripts" / "audit_subagent_tools.py"
VERIFY_RUN = SKILLS / "run-eval-question" / "scripts" / "verify_run.py"
VERIFY_GOLD = SKILLS / "build-eval-gold" / "scripts" / "verify_gold.py"
TAMPERED = SKILLS / "isolated-trace-check" / "scripts" / "make_tampered_version.py"


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *map(str, args)], cwd=helpers.ROOT, capture_output=True, text=True)


def tmpdir(test) -> Path:
    d = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, d, True)
    return d


def prepared_run(test) -> Path:
    """用 stage3 prepare 在暫存資料夾造出一個走到階段 3 的 run（含判斷）。"""
    d = tmpdir(test)
    pred = dict(helpers.read(helpers.FIX / "cashier_clean_prediction.json"), run_id=d.name)   # run_id 與資料夾名一致
    helpers.build_run(d, prediction=pred,
                      trace=helpers.read(helpers.FIX / "cashier_clean_trace.json"),
                      judge=helpers.read(helpers.FIX / "cashier_clean_judge.json"), prepare=True)
    return d



class AllScriptsHaveHelpAndSampleTest(unittest.TestCase):
    def test_help_and_sample(self):
        for script in (ISOLATED, VERIFY_RUN, VERIFY_GOLD, TAMPERED, AUDIT):
            for flag in ("--help", "--sample"):
                r = run(script, flag)
                self.assertEqual(r.returncode, 0, f"{script.name} {flag}\n{r.stderr}")
        json.loads(run(VERIFY_RUN, "--sample").stdout)


class PrepareIsolatedDirTest(unittest.TestCase):
    def test_a_real_trace_input_is_copied_alone_and_the_prompt_has_both_paths(self):
        run_dir, out = prepared_run(self), tmpdir(self) / "isolated"
        r = run(ISOLATED, run_dir, "--out", out, "--print-prompt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([p.name for p in out.iterdir()], ["trace_input.json"])            # 只有這一個檔
        self.assertEqual((out / "trace_input.json").read_bytes(), (run_dir / "trace_input.json").read_bytes())
        self.assertIn(str(out / "trace_input.json"), r.stdout)
        self.assertIn(str(out / "trace.json"), r.stdout)
        self.assertNotIn("{INPUT_FILE}", r.stdout)
        self.assertNotIn("{OUTPUT_FILE}", r.stdout)
        self.assertIn("ONLY the single input file", r.stdout)

    def test_an_input_that_mentions_gold_is_refused(self):
        d = tmpdir(self)
        (d / "trace_input.json").write_text(json.dumps({"answer_text": "x", "keypoints": ["K1"]}), encoding="utf-8")
        r = run(ISOLATED, d, "--out", d / "isolated")
        self.assertEqual(r.returncode, 1)
        self.assertIn("REFUSED", r.stderr)
        self.assertFalse((d / "isolated").exists())

    def test_a_directory_that_is_not_empty_is_refused(self):
        run_dir, out = prepared_run(self), tmpdir(self)
        (out / "something_else.txt").write_text("x", encoding="utf-8")
        r = run(ISOLATED, run_dir, "--out", out)
        self.assertEqual(r.returncode, 1)
        self.assertEqual([p.name for p in out.iterdir()], ["something_else.txt"])

    def test_a_missing_input_exits_2(self):
        self.assertEqual(run(ISOLATED, tmpdir(self)).returncode, 2)


def transcript(d: Path, calls) -> Path:
    """造一份子代理對話記錄（每行一個 JSON；另外混一行非 JSON 與一行沒有工具呼叫的訊息）。calls: [(tool, input dict)]"""
    lines = ["not json at all", json.dumps({"message": {"content": "plain text, no tool"}})]
    for name, inp in calls:
        lines.append(json.dumps({"message": {"content": [{"type": "text", "text": "thinking about the answer"},
                                                         {"type": "tool_use", "name": name, "input": inp}]}}, ensure_ascii=False))
    p = d / "t.output"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


class AuditSubagentToolsTest(unittest.TestCase):
    def setUp(self):
        self.d = tmpdir(self)
        self.inp, self.out = str(self.d / "iso" / "trace_input.json"), str(self.d / "iso" / "trace.json")
        self.clean = [("Read", {"file_path": self.inp}), ("Write", {"file_path": self.out, "content": "{}"}), ("SubagentHandback", {"message": "done"})]

    def audit(self, calls, *extra):
        return run(AUDIT, transcript(self.d, calls), "--input", self.inp, "--output", self.out, *extra)

    def test_read_input_write_output_handback_passes(self):
        r = self.audit(self.clean)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS (3 calls, 0 violations)", r.stdout)

    def test_the_transcript_text_and_tool_content_are_never_printed(self):
        r = self.audit(self.clean)
        self.assertNotIn("thinking about the answer", r.stdout)
        self.assertNotIn('"content"', r.stdout)

    def test_reading_another_file_is_a_violation(self):
        r = self.audit([("Read", {"file_path": self.inp}), ("Read", {"file_path": "/etc/hosts"})] + self.clean[1:])
        self.assertEqual(r.returncode, 1)
        self.assertIn("read a file other than the input file", r.stdout)

    def test_writing_another_file_is_a_violation(self):
        r = self.audit([self.clean[0], ("Write", {"file_path": str(self.d / "other.json")})])
        self.assertEqual(r.returncode, 1)
        self.assertIn("wrote a file other than the output file", r.stdout)

    def test_a_shell_command_a_search_and_a_listing_are_violations(self):
        for tool, inp in (("Bash", {"command": "ls /"}), ("Grep", {"pattern": "gold"}), ("Glob", {"pattern": "**/*"})):
            r = self.audit(self.clean + [(tool, inp)])
            self.assertEqual(r.returncode, 1, tool)
            self.assertIn("is not allowed", r.stdout)

    def test_a_path_spelled_differently_but_pointing_to_the_same_file_passes(self):
        r = self.audit([("Read", {"file_path": str(self.d / "iso" / "sub" / ".." / "trace_input.json")}), self.clean[1], self.clean[2]])
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_a_read_without_a_path_is_a_violation(self):
        self.assertEqual(self.audit([("Read", {})] + self.clean[1:]).returncode, 1)

    def test_no_tool_calls_or_a_missing_file_is_exit_2_not_a_pass(self):
        r = self.audit([])
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a pass", r.stderr)
        self.assertEqual(run(AUDIT, self.d / "nope.output", "--input", self.inp, "--output", self.out).returncode, 2)

    def test_json_output(self):
        r = self.audit(self.clean + [("Bash", {"command": "ls"})], "--json")
        data = json.loads(r.stdout)
        self.assertFalse(data["ok"])
        self.assertEqual((data["n_calls"], data["n_violations"]), (4, 1))
        self.assertEqual(data["calls"][3]["verdict"], "violation")


class VerifyRunTest(unittest.TestCase):
    def test_a_good_run_passes_and_a_leftover_manual_trace_is_only_a_warning(self):
        d = prepared_run(self)
        self.assertEqual(run(VERIFY_RUN, d).returncode, 0)
        (d / "trace.manual.json").write_text("{}", encoding="utf-8")
        r = run(VERIFY_RUN, d)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("non-isolated leftovers", r.stdout)

    def test_a_run_id_that_differs_from_the_folder_name_is_only_a_warning(self):
        d = prepared_run(self)
        pred = helpers.read(d / "prediction.json")
        pred["run_id"] = "someone-renamed-the-folder"
        helpers.write(d / "prediction.json", pred)
        r = run(VERIFY_RUN, d)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("differs from the folder name", r.stdout)

    def edit(self, fname, fn):
        d = prepared_run(self)
        obj = helpers.read(d / fname)
        fn(obj)
        helpers.write(d / fname, obj)
        return run(VERIFY_RUN, d)

    def test_an_unknown_claim_status_fails(self):
        r = self.edit("trace.json", lambda t: t["claims"][0].update(status="partly"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("status", r.stdout)

    def test_a_supported_claim_without_evidence_fails(self):
        r = self.edit("trace.json", lambda t: t["claims"][0].update(evidence=[]))
        self.assertEqual(r.returncode, 1)

    def test_evidence_that_points_to_an_unknown_item_fails(self):
        r = self.edit("trace.json", lambda t: t["claims"][0]["evidence"][0].update(item="E9"))
        self.assertEqual(r.returncode, 1)

    def test_a_keypoint_missing_from_the_judgement_fails(self):
        r = self.edit("judge.json", lambda j: j.update(keypoints=j["keypoints"][:2]))
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing keypoint K3", r.stdout)

    def test_a_link_to_a_claim_that_does_not_exist_fails(self):
        r = self.edit("judge.json", lambda j: j["keypoints"][0].update(claims=["c99"]))
        self.assertEqual(r.returncode, 1)

    def test_an_unknown_verdict_fails(self):
        r = self.edit("judge.json", lambda j: j["keypoints"][0].update(verdict="maybe"))
        self.assertEqual(r.returncode, 1)

    def test_a_missing_file_fails(self):
        d = prepared_run(self)
        (d / "judge.json").unlink()
        self.assertEqual(run(VERIFY_RUN, d).returncode, 1)
        self.assertEqual(run(VERIFY_RUN, d, "--stage", "prepare").returncode, 0)


class VerifyGoldTest(unittest.TestCase):
    def test_the_real_gold_passes(self):
        r = run(VERIFY_GOLD, helpers.GOLD)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(r.stdout.startswith("PASS"))
        self.assertTrue(json.loads(run(VERIFY_GOLD, helpers.GOLD, "--json").stdout)["ok"])

    def test_a_gold_with_a_quote_that_is_not_in_its_sources_fails(self):
        d = tmpdir(self)
        shutil.copytree(helpers.GOLD.parent / "sources", d / "sources")
        gold = helpers.read(helpers.GOLD)
        gold["keypoints"][0]["references"][0]["text"] = "編造的引文 62999"
        helpers.write(d / "gold.json", gold)
        r = run(VERIFY_GOLD, d / "gold.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("引文不在來源原文裡", r.stdout)

    def test_a_missing_gold_exits_1(self):
        self.assertEqual(run(VERIFY_GOLD, tmpdir(self) / "nope.json").returncode, 1)

    def test_every_real_gold_passes_without_advisories(self):
        for gold in sorted(helpers.EVAL.glob("*/gold.json")):
            r = run(VERIFY_GOLD, gold)
            self.assertEqual(r.returncode, 0, f"{gold}\n{r.stdout}")   # 電話號碼、編號沒有單位，不會被誤報

    def gold_with(self, edit):
        d = tmpdir(self)
        shutil.copytree(helpers.GOLD.parent / "sources", d / "sources")
        gold = helpers.read(helpers.GOLD)
        edit(gold)
        helpers.write(d / "gold.json", gold)
        return run(VERIFY_GOLD, d / "gold.json")

    def test_a_keypoint_with_two_numbers_and_units_gets_an_advisory(self):
        r = self.gold_with(lambda g: g["keypoints"][0].update(text="雙主修上限 31 學分、輔系上限 28 學分"))
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("ADVISORY", r.stdout)
        self.assertIn("more than one fact", r.stdout)

    def test_the_same_number_twice_or_a_phone_number_is_not_flagged(self):
        r = self.gold_with(lambda g: g["keypoints"][0].update(text="上限 25 學分，也就是 25 學分（電話 (02)2939-3091 分機 62120）"))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_a_hard_keypoint_nobody_can_hit_gets_an_advisory(self):
        def edit(g):
            kp = g["keypoints"][0]
            kp["acceptable_expressions"] = []
            kp.pop("value_check", None)
        r = self.gold_with(edit)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("can never hit it", r.stdout)

    def test_advisories_do_not_hide_real_problems(self):
        def edit(g):
            g["keypoints"][0]["text"] = "上限 31 學分、下限 12 學分"
            g["keypoints"][0]["references"][0]["text"] = "編造的引文 62999"
        r = self.gold_with(edit)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("引文不在來源原文裡", r.stdout)
        self.assertIn("ADVISORY", r.stdout)


class MakeTamperedVersionTest(unittest.TestCase):
    def base_run(self):
        d = tmpdir(self)
        helpers.write(d / "prediction.json", helpers.read(helpers.FIX / "cashier_clean_prediction.json"))
        return d

    def test_a_new_version_is_built_with_the_current_rules_and_stripped_evidence(self):
        target = tmpdir(self) / "tampered_vX"
        r = run(TAMPERED, helpers.TAMPER, target, "--base-run", self.base_run())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual({p.name for p in target.iterdir()}, {"answer.txt", "expected.json", "trace_input.json", "results"})
        ti = helpers.read(target / "trace_input.json")
        self.assertEqual(ti["answer_text"], (helpers.TAMPER / "answer.txt").read_text(encoding="utf-8").rstrip("\n"))
        self.assertNotIn("來源：", ti["evidence_items"][0]["text"])                       # v1 的證據含來源行，新版剝掉了
        self.assertEqual(len(ti["stripped_not_scored"]["evidence_source_lines"]), 3)
        self.assertGreater(len(ti["output_format"]["rules"]), len(helpers.read(helpers.TAMPER / "trace_input.json")["output_format"]["rules"]))
        self.assertEqual(helpers.read(target / "expected.json")["version"], "tampered_vX")
        self.assertEqual(len(helpers.read(target / "expected.json")["items"]), 9)

    def test_an_existing_target_is_never_overwritten(self):
        target = tmpdir(self)
        r = run(TAMPERED, helpers.TAMPER, target, "--base-run", self.base_run())
        self.assertEqual(r.returncode, 1)
        self.assertIn("never overwritten", r.stderr)

    def test_a_missing_source_exits_2(self):
        r = run(TAMPERED, tmpdir(self), tmpdir(self) / "new", "--base-run", self.base_run())
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
