"""
真實批次（evaluation/batch.py）的測試：全部離線，不呼叫 LLM、不上網。
子程序用假的（python -c …）或注入的 runner 取代 run_system，所以不會 import agentic_rag、不會啟動 Chromium。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import helpers

import batch  # noqa: E402  (helpers 已把 evaluation/ 放進 sys.path)
import run_system  # noqa: E402


def write(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    helpers.write(path, obj)


def tmpdir(test) -> Path:
    d = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, d, True)
    return d


def fake_root(test, names=("qa", "qb", "qc")) -> Path:
    """一個假的 evaluation 資料夾：batch_questions.json 與每題一個 gold.json。"""
    root = tmpdir(test)
    qs = [{"id": i + 1, "question": n, "short": n, "group": "Factual Questions"} for i, n in enumerate(names)]
    write(root / "batch_questions.json", {"questions": qs})
    for n in names:
        write(root / n / "gold.json", {"query_id": n, "query": "問" + n, "keypoints": []})
    return root


def ok_runner(calls):
    """假的子程序：像 run_system 一樣把 prediction.json 寫進 --run-id 指定的資料夾。"""
    def runner(cmd, timeout, log_path, env=None):
        gold = Path(cmd[2])
        run_id = cmd[cmd.index("--run-id") + 1]
        calls.append({"cmd": cmd, "env": env})
        write(gold.parent / "runs" / run_id / "prediction.json", {"run_id": run_id, "status": "ok", "model": "m", "answer_body": "答"})
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("ok")
        return {"returncode": 0, "timed_out": False, "elapsed": 1.5, "tail": "ok"}
    return runner


class QuestionsFileTest(unittest.TestCase):
    def test_real_file_matches_preview_and_gold_folders(self):
        qs = batch.load_questions()
        self.assertEqual([q["id"] for q in qs], list(range(1, 12)))
        preview = json.loads((helpers.EVAL / "dashboard" / "sample" / "preview_cases.json").read_text(encoding="utf-8"))["cases"]
        self.assertEqual([(q["id"], q["question"], q["group"]) for q in qs], [(c["id"], c["question"], c["group"]) for c in preview])
        for q in qs:
            self.assertTrue((helpers.EVAL / q["question"] / "gold.json").exists(), q["question"])

    def test_only_filters_and_rejects_unknown(self):
        self.assertEqual([q["id"] for q in batch.load_questions({2, 5})], [2, 5])
        with self.assertRaises(SystemExit):
            batch.load_questions({99})


class BatchIdTest(unittest.TestCase):
    def test_numbering(self):
        d = tmpdir(self)
        self.assertEqual(batch.new_batch_id(d / "none"), "batch01")
        (d / "batch01").mkdir()
        (d / "batch04").mkdir()
        (d / "other").mkdir()
        self.assertEqual(batch.new_batch_id(d), "batch05")


class PreflightTest(unittest.TestCase):
    def test_real_golds_pass_and_live_switch_is_checked(self):
        qs = batch.load_questions()
        errors, _ = batch.preflight(qs, live=True, env={})
        self.assertEqual(errors, [])
        errors, _ = batch.preflight(qs[:1], live=True, env={"LIVE_FETCH": "off"})
        self.assertTrue(any("LIVE_FETCH" in e for e in errors))
        errors, _ = batch.preflight(qs[:1], live=False, env={"LIVE_FETCH": "off"})
        self.assertEqual(errors, [])                      # 不查現場時，總開關無所謂

    def test_missing_gold_is_an_error(self):
        root = fake_root(self)
        (root / "qb" / "gold.json").unlink()
        errors, _ = batch.preflight(batch.load_questions(root=root), live=False, root=root, env={})
        self.assertTrue(any("qb" in e and "gold.json" in e for e in errors))


class RunChildTest(unittest.TestCase):
    def test_success_and_log(self):
        d = tmpdir(self)
        res = batch.run_child([sys.executable, "-c", "print('hello')"], 20, d / "l.log")
        self.assertEqual((res["returncode"], res["timed_out"]), (0, False))
        self.assertIn("hello", (d / "l.log").read_text())

    def test_timeout_kills_the_whole_process_group(self):
        d = tmpdir(self)
        pidfile = d / "child.pid"
        code = ("import subprocess,sys,time\n"
                f"c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
                f"open({str(pidfile)!r},'w').write(str(c.pid))\n"
                "time.sleep(60)\n")
        t0 = time.time()
        res = batch.run_child([sys.executable, "-c", code], 2, d / "l.log")
        self.assertTrue(res["timed_out"])
        self.assertLess(time.time() - t0, 15)
        pid = int(pidfile.read_text())
        time.sleep(0.5)
        with self.assertRaises(ProcessLookupError):       # 孫行程（等於 Chromium）也要被殺
            os.kill(pid, 0)

    def test_classify(self):
        d = tmpdir(self)
        ok = {"returncode": 0, "timed_out": False, "tail": ""}
        self.assertEqual(batch.classify(dict(ok, timed_out=True), d), "timeout")
        self.assertEqual(batch.classify(ok, d), "error")                       # 結束碼 0 但沒有 prediction.json
        write(d / "prediction.json", {})
        self.assertEqual(batch.classify(ok, d), "ok")
        self.assertEqual(batch.classify({"returncode": 1, "timed_out": False, "tail": "status code: 402 Payment Required"}, tmpdir(self)), "quota")
        self.assertEqual(batch.classify({"returncode": 1, "timed_out": False, "tail": "page 62402 not found"}, tmpdir(self)), "error")


class RunBatchTest(unittest.TestCase):
    def setUp(self):
        self.root = fake_root(self)
        self.qs = batch.load_questions(root=self.root)
        self.bdir = tmpdir(self) / "batch01"
        self.said = []

    def run_it(self, runner, **kw):
        return batch.run_batch(self.bdir, self.qs, True, True, 600, runner=runner, root=self.root, say=self.said.append, **kw)

    def test_runs_in_order_and_passes_live_flags(self):
        calls = []
        m = self.run_it(ok_runner(calls))
        self.assertEqual([e["status"] for e in m["questions"]], ["ok"] * 3)
        self.assertEqual([e["run_id"] for e in m["questions"]], ["run01"] * 3)
        for c in calls:
            self.assertEqual(c["cmd"][c["cmd"].index("--live") + 1], "on")
            self.assertEqual(c["cmd"][c["cmd"].index("--browser") + 1], "on")
            self.assertEqual(c["env"]["LIVE_LOG"], "info")
        self.assertEqual(json.loads((self.bdir / "manifest.json").read_text())["batch_id"], "batch01")

    def test_timeout_leaves_a_stub_run_and_batch_continues(self):
        calls = []
        good = ok_runner(calls)

        def runner(cmd, timeout, log_path, env=None):
            if "qb" in cmd[2]:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text("slow")
                return {"returncode": -9, "timed_out": True, "elapsed": 600.0, "tail": "slow"}
            return good(cmd, timeout, log_path, env)
        m = self.run_it(runner)
        self.assertEqual([e["status"] for e in m["questions"]], ["ok", "timeout", "ok"])
        stub = json.loads((self.root / "qb" / "runs" / "run01" / "prediction.json").read_text())
        self.assertEqual((stub["status"], stub["answer_body"], stub["failure"]["timeout_seconds"]), ("timeout", "", 600))

    def test_quota_stops_the_batch_and_leaves_no_run(self):
        calls = []
        good = ok_runner(calls)

        def runner(cmd, timeout, log_path, env=None):
            if "qb" in cmd[2]:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text("402")
                return {"returncode": 1, "timed_out": False, "elapsed": 3.0, "tail": "Error code: 402 Payment Required"}
            return good(cmd, timeout, log_path, env)
        m = self.run_it(runner)
        self.assertEqual([e["status"] for e in m["questions"]], ["ok", "quota"])      # qc 沒有開始
        self.assertFalse((self.root / "qb" / "runs").exists())                       # 沒有留下空的 run
        self.assertEqual(len(calls), 1)

    def test_resume_skips_ok_and_failed_but_reruns_quota(self):
        calls = []
        good = ok_runner(calls)
        state = {"qb": "timeout", "qc": "quota"}

        def runner(cmd, timeout, log_path, env=None):
            q = Path(cmd[2]).parent.name
            if state.get(q) == "timeout":
                return {"returncode": -9, "timed_out": True, "elapsed": 600.0, "tail": ""}
            if state.get(q) == "quota":
                return {"returncode": 1, "timed_out": False, "elapsed": 1.0, "tail": "402"}
            return good(cmd, timeout, log_path, env)
        self.run_it(runner)                                   # qa ok、qb timeout、qc quota
        calls.clear()
        state.clear()
        m = self.run_it(runner)                               # 接續：只有 qc 會再跑
        self.assertEqual([Path(c["cmd"][2]).parent.name for c in calls], ["qc"])
        self.assertEqual([e["status"] for e in m["questions"]], ["ok", "timeout", "ok"])
        calls.clear()
        self.run_it(runner, retry_failed=True)                # 要求重跑失敗的：qb 會再跑
        self.assertEqual([Path(c["cmd"][2]).parent.name for c in calls], ["qb"])


class StatusAndExportTest(unittest.TestCase):
    def test_status_reads_files(self):
        root = fake_root(self)
        bdir = tmpdir(self)
        batch._write(bdir / "batch01" / "manifest.json", {"batch_id": "batch01", "questions": [
            {"id": 1, "question": "qa", "run_id": "run01", "status": "ok", "elapsed_seconds": 5.0},
            {"id": 2, "question": "qb", "run_id": "run01", "status": "timeout", "elapsed_seconds": 600.0}]})
        write(root / "qa" / "runs" / "run01" / "prediction.json", {})
        write(root / "qa" / "runs" / "run01" / "trace.json", {})
        self.assertEqual(batch.question_stage(root / "qa", {"status": "ok", "run_id": "run01"}), "已回推，待判斷")
        self.assertEqual(batch.question_stage(root / "qc", None), "未跑")
        lines = []
        self.assertEqual(batch.cmd_status("batch01", root=root, batches=bdir, say=lines.append), 0)
        self.assertIn("已回推，待判斷", lines[0])
        self.assertIn("timeout", lines[1])
        self.assertIn("未跑", lines[2])

    def test_cases_from_manifest_skips_questions_without_run(self):
        root = fake_root(self)
        m = {"batch_id": "batch01", "questions": [{"id": 1, "question": "qa", "run_id": "run02", "status": "ok"},
                                                   {"id": 3, "question": "qc", "run_id": None, "status": "quota"}]}
        c = batch.cases_from_manifest(m, root)
        self.assertEqual([(x["question"], x["dir"]) for x in c["cases"]], [("qa", "runs/run02")])

    def test_live_observations_reads_markers(self):
        pred = {"context": [{"text": "x [live:src status=live_new kind=page checked=2026-11-15T10:00 snap=2026-08-25 tls=0 mf=https%3A%2F%2Fcashier.nccu.edu.tw%2Fold url=https://nccuga.nccu.edu.tw/new]\n"
                                     "y [live:src status=snapshot_fallback kind=page checked=- snap=2026-08-25 tls=0 mv=https%3A%2F%2Fnccuga.nccu.edu.tw%2Fnew url=https://aff.nccu.edu.tw/old]"}]}
        o = batch.live_observations(pred)
        self.assertEqual(o["states"], {"live_new": 1, "snapshot_fallback": 1})
        self.assertEqual([m["moved_from"] or m["moved_to"] for m in o["moved"]], ["https://cashier.nccu.edu.tw/old", "https://nccuga.nccu.edu.tw/new"])

    def test_summary_lists_problems_and_next_step(self):
        bdir = tmpdir(self)
        m = {"batch_id": "batch01", "created_at": "t", "live": True, "browser": True, "timeout_seconds": 600, "model": "m", "git": {"commit": "abc"}}
        rows = [{"id": 1, "question": "cashier_contact", "status": "ok", "run_id": "run02", "elapsed": 20.0, "answer_chars": 100, "accuracy": "1/2"},
                {"id": 2, "question": "course_limit", "status": "timeout", "run_id": "run01", "elapsed": 600.0}]
        text = batch.write_summary(bdir, m, rows).read_text(encoding="utf-8")
        self.assertIn("需要你看的", text)
        self.assertIn("Q2 course_limit：timeout", text)
        self.assertIn("等使用者說", text)


class FailedRunExportTest(unittest.TestCase):
    def test_timed_out_run_becomes_a_row_with_no_metrics_and_a_status(self):
        sys.path.insert(0, str(helpers.EVAL / "dashboard"))
        import export_scores
        root = tmpdir(self)
        (root / "cashier_contact").mkdir()
        shutil.copy(helpers.GOLD, root / "cashier_contact" / "gold.json")
        run_dir = root / "cashier_contact" / "runs" / "run09"
        res = {"returncode": -9, "timed_out": True, "elapsed": 600.0, "tail": "stuck"}
        batch.write_failure_stub(run_dir, {"question": "cashier_contact"}, "timeout", res, "batch01", "abc", True, True, 600)
        entry = {"id": 1, "question": "cashier_contact", "short": "出納組電話", "group": "Factual Questions", "dir": "runs/run09"}
        row = export_scores.build_row(entry, root)
        self.assertEqual(row["status"], "timeout")
        self.assertEqual(row["source"], "real")
        self.assertIsNone(row["keypoint"])
        self.assertIsNone(row["accuracy"])
        self.assertEqual(row["run"]["run_id"], "run09")
        self.assertTrue(row["run"]["live"])
        self.assertEqual(row["prediction"]["content"], "")
        json.dumps(row, ensure_ascii=False)                # 可以寫成 jsonl

    def test_run_without_scores_and_without_failure_still_raises(self):
        sys.path.insert(0, str(helpers.EVAL / "dashboard"))
        import export_scores
        root = tmpdir(self)
        (root / "cashier_contact").mkdir()
        shutil.copy(helpers.GOLD, root / "cashier_contact" / "gold.json")
        write(root / "cashier_contact" / "runs" / "run01" / "prediction.json", {"run_id": "run01", "status": "ok"})
        with self.assertRaises(FileNotFoundError):
            export_scores.build_row({"id": 1, "question": "cashier_contact", "short": "s", "group": "g", "dir": "runs/run01"}, root)


class EndToEndOfflineTest(unittest.TestCase):
    def test_score_summary_and_export_from_an_existing_run(self):
        root = tmpdir(self)
        (root / "cashier_contact").mkdir()
        shutil.copy(helpers.GOLD, root / "cashier_contact" / "gold.json")
        shutil.copytree(helpers.EVAL / "cashier_contact" / "runs" / "run01", root / "cashier_contact" / "runs" / "run01")
        write(root / "batch_questions.json", {"questions": [{"id": 1, "question": "cashier_contact", "short": "出納組電話", "group": "Factual Questions"}]})
        m = {"batch_id": "batch01", "created_at": "t", "git": {"commit": "x"}, "live": True, "browser": True, "timeout_seconds": 600, "model": "m",
             "questions": [{"id": 1, "question": "cashier_contact", "run_id": "run01", "status": "ok", "elapsed_seconds": 14.0}]}
        bd = root / "batches" / "batch01"
        batch._write(bd / "manifest.json", m)
        rows = batch.score_offline(m, root=root)
        self.assertEqual((rows[0]["status"], rows[0]["accuracy"]), ("ok", "3/3"))
        self.assertNotIn("error", rows[0])
        self.assertTrue((root / "cashier_contact" / "runs" / "run01" / "trace_input.json").exists())
        self.assertIn("| Q1 |", batch.write_summary(bd, m, rows).read_text(encoding="utf-8"))
        self.assertEqual(batch.cmd_export("batch01", root=root, batches=root / "batches", say=lambda s: None), 0)
        jl = [json.loads(x) for x in (bd / "dashboard.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual((len(jl), jl[0]["source"], jl[0]["run"]["run_id"]), (1, "real", "run01"))
        report = (bd / "report.md").read_text(encoding="utf-8")
        self.assertIn("live 與轉址觀察", report)
        self.assertIn("## 總表", report)
        self.assertIn("| 1 | 出納組電話 | run01 |", report)
        self.assertFalse((bd / "dashboard_all.jsonl").exists())              # no cases_all.json: nothing extra is written
        # a cases_all.json (the eleven-question list that borrows runs from another batch) drives the table and dashboard_all.jsonl too
        batch._write(bd / "cases_all.json", {"note": "t", "cases": [{"id": 1, "question": "cashier_contact", "short": "出納組電話",
                                                                       "group": "Factual Questions", "dir": "runs/run01"}]})
        self.assertEqual(batch.cmd_export("batch01", root=root, batches=root / "batches", say=lambda s: None), 0)
        self.assertEqual(len((bd / "dashboard_all.jsonl").read_text(encoding="utf-8").splitlines()), 1)
        self.assertIn("來自 `cases_all.json`", (bd / "report.md").read_text(encoding="utf-8"))


class RerunTest(unittest.TestCase):
    """batch.py rerun：同一批裡某幾題再跑一次。離線；runner 與 scorer 都是假的。"""

    def setUp(self):
        self.root = fake_root(self)
        self.batches = self.root / "batches"
        self.bd = self.batches / "batch01"
        self.said = []
        self.scored = []
        from unittest import mock
        p = mock.patch.object(batch, "preflight", lambda qs, live, root=None, env=None: ([], []))      # the fake golds have no sources to check
        p.start()
        self.addCleanup(p.stop)
        for n in ("qa", "qb", "qc"):
            write(self.root / n / "runs" / "run01" / "prediction.json", {"run_id": "run01", "status": "ok", "live": True})
        m = {"batch_id": "batch01", "created_at": "t", "git": {"commit": "x"}, "live": False, "browser": False, "timeout_seconds": 600, "model": "m",
             "questions": [{"id": 1, "question": "qa", "run_id": "run01", "status": "ok", "elapsed_seconds": 5.0, "at": "a1"},
                           {"id": 2, "question": "qb", "run_id": "run01", "status": "error", "elapsed_seconds": 6.0, "at": "a2", "note": "出錯"},
                           {"id": 3, "question": "qc", "run_id": "run01", "status": "ok", "elapsed_seconds": 7.0, "at": "a3"}]}
        write(self.bd / "manifest.json", m)
        write(self.bd / "cases_all.json", {"note": "t", "cases": [{"id": i, "question": n, "short": n, "group": "g", "dir": "runs/run01"}
                                                                  for i, n in ((1, "qa"), (2, "qb"), (3, "qc"))]})

    def args(self, only="2", reason="修好 F35", run=True, timeout=600):
        import argparse
        return argparse.Namespace(batch="batch01", only=only, reason=reason, timeout=timeout, label="", run=run)

    def go(self, runner=None, **kw):
        calls = []
        rc = batch.cmd_rerun(self.args(**kw), batches=self.batches, root=self.root, runner=runner or ok_runner(calls),
                             scorer=lambda m, root=None, say=None: self.scored.append([e["question"] for e in m["questions"]]), say=self.said.append)
        return rc, calls

    def manifest(self):
        return json.loads((self.bd / "manifest.json").read_text(encoding="utf-8"))

    def test_without_run_it_is_a_dry_run_that_changes_nothing(self):
        before = (self.bd / "manifest.json").read_text(encoding="utf-8")
        rc, calls = self.go(run=False)
        self.assertEqual((rc, calls), (0, []))
        self.assertEqual((self.bd / "manifest.json").read_text(encoding="utf-8"), before)
        self.assertFalse((self.root / "qb" / "runs" / "run02").exists())
        self.assertIn("預演結束", "\n".join(self.said))

    def test_a_reason_is_required(self):
        self.assertEqual(self.go(reason="  ")[0], 2)
        self.assertEqual(self.scored, [])

    def test_a_question_that_is_not_in_the_manifest_is_refused(self):
        m = self.manifest()
        m["questions"] = m["questions"][:2]
        write(self.bd / "manifest.json", m)
        rc, calls = self.go(only="3")
        self.assertEqual((rc, calls), (2, []))
        self.assertIn("沒有這些題", "\n".join(self.said))

    def test_a_rerun_replaces_the_failed_run_and_keeps_the_history(self):
        rc, calls = self.go(only="2")
        self.assertEqual(rc, 0)
        c = calls[0]["cmd"]
        self.assertEqual((c[c.index("--run-id") + 1], c[c.index("--live") + 1], c[c.index("--browser") + 1]), ("run02", "off", "off"))   # the batch's own live and browser settings
        self.assertIn("rerun 修好 F35", c[c.index("--label") + 1])
        e = {x["question"]: x for x in self.manifest()["questions"]}
        self.assertEqual((e["qb"]["run_id"], e["qb"]["status"]), ("run02", "ok"))
        self.assertEqual([a["run_id"] for a in e["qb"]["attempts"]], ["run01"])
        self.assertEqual((e["qb"]["first_attempt"]["run_id"], e["qb"]["first_attempt"]["status"]), ("run01", "error"))
        self.assertIn("修好 F35", e["qb"]["note"])
        self.assertEqual(e["qa"]["run_id"], "run01")                                           # other questions are not touched
        self.assertTrue((self.root / "qb" / "runs" / "run01" / "prediction.json").exists())   # the old run stays
        rr = self.manifest()["reruns"]
        self.assertEqual((len(rr), rr[0]["questions"], rr[0]["reason"]), (1, ["Q2"], "修好 F35"))
        cases = {c["question"]: c["dir"] for c in json.loads((self.bd / "cases_all.json").read_text(encoding="utf-8"))["cases"]}
        self.assertEqual((cases["qb"], cases["qa"]), ("runs/run02", "runs/run01"))
        self.assertEqual(self.scored, [["qb"]])                                                # only the rerun question is scored offline

    def test_a_second_rerun_appends_to_the_attempts_and_the_reruns(self):
        self.go(only="2", reason="第一次重跑")
        self.go(only="2", reason="第二次重跑")
        e = {x["question"]: x for x in self.manifest()["questions"]}["qb"]
        self.assertEqual((e["run_id"], [a["run_id"] for a in e["attempts"]]), ("run03", ["run01", "run02"]))
        self.assertEqual(e["first_attempt"]["run_id"], "run01")
        self.assertEqual([r["reason"] for r in self.manifest()["reruns"]], ["第一次重跑", "第二次重跑"])

    def test_a_failed_rerun_keeps_the_earlier_successful_run(self):
        def failing(cmd, timeout, log_path, env=None):
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("boom")
            return {"returncode": 1, "timed_out": False, "elapsed": 2.0, "tail": "Traceback boom"}
        rc, _ = self.go(only="1", runner=failing)
        e = {x["question"]: x for x in self.manifest()["questions"]}["qa"]
        self.assertEqual((e["run_id"], e["status"]), ("run01", "ok"))                          # the good run stays the current one
        self.assertEqual((e["attempts"][-1]["run_id"], e["attempts"][-1]["status"]), ("run02", "error"))
        self.assertTrue((self.root / "qa" / "runs" / "run02" / "prediction.json").exists())   # the failure stub is kept as a record
        self.assertEqual(self.scored, [])
        cases = {c["question"]: c["dir"] for c in json.loads((self.bd / "cases_all.json").read_text(encoding="utf-8"))["cases"]}
        self.assertEqual(cases["qa"], "runs/run01")

    def test_quota_stops_and_leaves_the_manifest_alone(self):
        def quota(cmd, timeout, log_path, env=None):
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("402")
            return {"returncode": 1, "timed_out": False, "elapsed": 1.0, "tail": "status code: 402 Payment Required"}
        before = (self.bd / "manifest.json").read_text(encoding="utf-8")
        rc, _ = self.go(only="1,2", runner=quota)
        self.assertEqual((self.bd / "manifest.json").read_text(encoding="utf-8"), before)
        self.assertEqual(self.scored, [])

    def test_the_old_object_form_of_reruns_and_first_attempt_are_still_read(self):
        m = self.manifest()
        m["reruns"] = {"at": "d", "after": "舊理由", "git": "g", "questions": ["Q1"], "note": "n"}
        m["questions"][1]["first_attempt"] = {"run_id": "run00", "status": "error", "elapsed_seconds": 1.0, "at": "z"}
        write(self.bd / "manifest.json", m)
        self.go(only="2")
        m2 = self.manifest()
        self.assertEqual([r["reason"] for r in m2["reruns"]], ["舊理由", "修好 F35"])
        e = {x["question"]: x for x in m2["questions"]}["qb"]
        self.assertEqual([a["run_id"] for a in e["attempts"]], ["run00", "run01"])

    def test_normalise_reruns_reads_none_object_and_list(self):
        self.assertEqual(batch.normalise_reruns({}), [])
        self.assertEqual(batch.normalise_reruns({"reruns": {"at": "d", "after": "x", "questions": ["Q1"]}})[0]["reason"], "x")
        self.assertEqual(batch.normalise_reruns({"reruns": [{"reason": "a"}, {"reason": "b"}]}), [{"reason": "a"}, {"reason": "b"}])


class AttemptsTest(unittest.TestCase):
    """「第幾次」：只算 live 開的真實 run；live 關的早期 run 另計，不算在內。"""

    def make(self, preds):
        q = tmpdir(self) / "q"
        for name, pred in preds.items():
            write(q / "runs" / name / "prediction.json", pred)
        return q

    def test_counts_only_live_runs_and_marks_the_one_used(self):
        q = self.make({"run01": {"live": False}, "run02": {"live": True, "status": "error"}, "run03": {"live": True, "status": "ok"}})
        a = batch.attempts_of(q, "run03")
        self.assertEqual((a["n"], a["total"], a["offline"]), (2, 2, 1))
        self.assertEqual(a["history"], [("run02", "error", False), ("run03", "ok", True)])
        self.assertEqual(batch.attempt_text(a), "第 2 次（共 2 次）")
        self.assertIn("run02 error、run03 ok（用這個）", batch.attempt_text(a, short=False))
        self.assertIn("1 個 live 關的早期 run 不算", batch.attempt_text(a, short=False))

    def test_a_single_run_is_attempt_one_of_one(self):
        a = batch.attempts_of(self.make({"run01": {"live": True}}), "run01")
        self.assertEqual((a["n"], a["total"]), (1, 1))

    def test_a_run_that_is_not_live_has_no_attempt_number(self):
        a = batch.attempts_of(self.make({"run01": {"live": False}}), "run01")
        self.assertIsNone(a["n"])
        self.assertIn("不是 live 真實 run", batch.attempt_text(a))

    def test_the_report_table_and_each_question_say_which_attempt(self):
        root = tmpdir(self)
        (root / "cashier_contact").mkdir()
        shutil.copy(helpers.GOLD, root / "cashier_contact" / "gold.json")
        shutil.copytree(helpers.EVAL / "cashier_contact" / "runs" / "run01", root / "cashier_contact" / "runs" / "run01")
        write(root / "batch_questions.json", {"questions": [{"id": 1, "question": "cashier_contact", "short": "出納組電話", "group": "Factual Questions"}]})
        m = {"batch_id": "batch01", "created_at": "t", "git": {"commit": "x"}, "live": True, "browser": True, "timeout_seconds": 600, "model": "m",
             "questions": [{"id": 1, "question": "cashier_contact", "run_id": "run01", "status": "ok", "elapsed_seconds": 14.0}]}
        bd = root / "batches" / "batch01"
        batch._write(bd / "manifest.json", m)
        batch.cmd_export("batch01", root=root, batches=root / "batches", say=lambda s: None)
        report = (bd / "report.md").read_text(encoding="utf-8")
        self.assertIn("| 第幾次 |", report)
        self.assertRegex(report, r"\| 1 \| 出納組電話 \| run01 \| 第 \d+ 次（共 \d+ 次）|\| 1 \| 出納組電話 \| run01 \| —（不是 live 真實 run）")
        self.assertIn("- 第幾次：", report)


class CliSafetyTest(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ, LIVE_BROWSER="off")
        return subprocess.run([sys.executable, str(helpers.EVAL / "batch.py"), *args], capture_output=True, text=True, env=env, cwd=helpers.ROOT)

    def test_run_without_flag_is_a_dry_run_and_creates_nothing(self):
        before = set((helpers.EVAL / "batches").glob("*")) if (helpers.EVAL / "batches").exists() else set()
        r = self.run_cli("run", "--only", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("預演結束，沒有送出任何請求", r.stdout)
        after = set((helpers.EVAL / "batches").glob("*")) if (helpers.EVAL / "batches").exists() else set()
        self.assertEqual(before, after)

    def test_plan_states_live_and_ollama(self):
        r = self.run_cli("plan", "--only", "1,2")
        self.assertIn("會對 nccu.edu.tw 送請求", r.stdout)
        self.assertIn("會呼叫 ollama", r.stdout)


class RunSystemFlagsTest(unittest.TestCase):
    def test_live_on_is_refused_when_kill_switch_is_off(self):
        env = dict(os.environ, LIVE_FETCH="off", LIVE_BROWSER="off")
        r = subprocess.run([sys.executable, str(helpers.EVAL / "run_system.py"), str(helpers.GOLD), "--live", "on"],
                           capture_output=True, text=True, env=env, cwd=helpers.ROOT, timeout=120)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("總開關", r.stderr)                 # 在 import agentic_rag 之前就停，沒有呼叫 LLM、沒有請求

    def test_run_id_and_flags_exist(self):
        r = subprocess.run([sys.executable, str(helpers.EVAL / "run_system.py"), "--help"], capture_output=True, text=True, cwd=helpers.ROOT, timeout=120)
        for flag in ("--live", "--browser", "--run-id"):
            self.assertIn(flag, r.stdout)


if __name__ == "__main__":
    unittest.main()
