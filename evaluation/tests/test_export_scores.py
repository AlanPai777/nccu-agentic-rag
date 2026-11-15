"""evaluation/dashboard/export_scores.py：把各題的評測結果組成 dashboard 的 .jsonl。離線，不呼叫 LLM。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dashboard"))

import export_scores  # noqa: E402


def write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def make_question(root: Path, name="q_demo", case="tests/pipeline_setup/complete", stage3=True, query_type="procedure"):
    q = root / name
    write(q / "gold.json", {"query": "示範題目", "query_type": query_type, "content": "標準答案",
                            "keypoints": [{"id": "K1", "text": "事實一", "required": True, "kind": "hard"},
                                          {"id": "K2", "text": "事實二", "required": False, "kind": "semantic"}]})
    c = q / case
    scores = {"run_id": "complete", "system_version": "hypothetical",
              "rouge_l": {"p": 0.4, "r": 0.5, "f": 0.45},
              "accuracy_rule": {"hard_keypoints": 1, "hit": 1, "accuracy": 1.0},
              "context": {"sentence": {"p": 0.1, "r": 1.0, "f": 0.18}, "words": {"p": 0.2, "r": 0.9, "f": 0.33}},
              "funnel": [], "warnings": [], "disagreements": []}
    if stage3:
        scores.update({"keypoint": {"completeness": 1.0, "hallucination": 0.0, "irrelevance": 0.0},
                       "fact_unit": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
                       "claim_unit": {"claims": 2, "correct_claims": 2, "precision": 1.0, "recall": 1.0, "f1": 1.0},
                       "evidence_support": {"rate": 1.0, "supported": 2, "claims": 2, "unsupported_claims": []},
                       "ungrounded_correct_keypoints": []})
        write(c / "judge.json", {"keypoints": [{"id": "K1", "verdict": "relevant", "claims": ["c1"], "reason": "有寫"},
                                               {"id": "K2", "verdict": "relevant", "claims": ["c2"], "reason": "有寫"}]})
        write(c / "trace.json", {"claims": [{"id": "c1", "answer_span": "甲", "status": "supported", "why": ""},
                                            {"id": "c2", "answer_span": "乙", "status": "supported", "why": ""}]})
    write(c / "scores.json", scores)
    write(c / "prediction.json", {"answer_body": "答案正文", "label": "測試", "model": "m", "trace": {"query_type": "knowledge"}})
    return {"id": 3, "question": name, "short": "示範", "group": "Factual Questions", "dir": case}


class TestExportScores(unittest.TestCase):
    def test_row_has_wsm_fields_and_ours(self):
        with tempfile.TemporaryDirectory() as d:
            row = export_scores.build_row(make_question(Path(d)), Path(d))
        self.assertEqual(row["query"], {"query_id": 3, "short": "示範", "content": "示範題目", "query_type": "procedure"})
        self.assertEqual(row["group"], "Factual Questions")
        self.assertEqual(row["completeness"], 1.0)
        self.assertEqual(row["ROUGELScore"], 0.45)
        self.assertEqual((row["Sentences_Recall"], row["Words_Precision"]), (1.0, 0.2))
        self.assertEqual(row["accuracy"], {"hit": 1, "total": 1, "value": 1.0})
        self.assertEqual(row["evidence"]["supported"], 2)
        self.assertEqual(row["claim"]["correct"], 2)
        self.assertEqual([k["verdict"] for k in row["responses"]["keypoints"]], ["relevant", "relevant"])
        self.assertEqual(row["prediction"]["content"], "答案正文")

    def test_routing_is_expected_from_gold_and_router_from_prediction(self):
        with tempfile.TemporaryDirectory() as d:
            row = export_scores.build_row(make_question(Path(d)), Path(d))
        self.assertEqual(row["routing"], {"expected": "procedure", "router": "knowledge"})

    def test_source_follows_the_directory(self):
        with tempfile.TemporaryDirectory() as d:
            real = export_scores.build_row(make_question(Path(d), name="a", case="runs/run01"), Path(d))
            hyp = export_scores.build_row(make_question(Path(d), name="b", case="tests/pipeline_setup/partial"), Path(d))
        self.assertEqual((real["source"], hyp["source"]), ("real", "hypothetical"))
        self.assertEqual(hyp["case"], "partial")

    def test_missing_stage3_values_are_null_not_zero(self):
        with tempfile.TemporaryDirectory() as d:
            e = make_question(Path(d), stage3=False)
            c = Path(d) / e["question"] / e["dir"]
            (c / "scores.json").rename(c / "scores.stage2.json")
            row = export_scores.build_row(e, Path(d))
        for k in ("completeness", "hallucination", "irrelevance", "keypoint", "claim", "evidence"):
            self.assertIsNone(row[k], k)
        self.assertEqual(row["accuracy"]["total"], 1)               # 階段 2 的仍然有
        self.assertIsNone(row["responses"]["keypoints"])

    def test_missing_gold_or_scores_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):
                export_scores.build_row({"id": 1, "question": "nope", "short": "x", "group": "g", "dir": "runs/run01"}, Path(d))

    def test_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            e = make_question(Path(d))
            spec = Path(d) / "cases.json"
            write(spec, {"cases": [e, e]})
            with self.assertRaises(ValueError):
                export_scores.export(spec, Path(d) / "out.jsonl", Path(d))


class TestReferencesAndAlternatives(unittest.TestCase):
    """展開區要用的三組資料：系統讀進來的內容、gold 的原文出處（標系統有沒有讀到）、登記表型 keypoint 的替代寫法。"""

    def _question_with_refs(self, root: Path, context_text: str, funnel=None):
        e = make_question(root)
        q = root / e["question"]
        gold = json.loads((q / "gold.json").read_text(encoding="utf-8"))
        gold["keypoints"][0]["references"] = [
            {"text": "可以找到的原文", "source_url": "https://x/a", "source_kind": "snapshot", "as_of": "2026-08"},
            {"text": "可以找到的原文", "source_url": "https://x/a", "source_kind": "live", "as_of": "2026-11-14"}]
        gold["keypoints"][1]["references"] = [{"text": "讀不到的原文", "source_url": "https://x/b", "source_kind": "snapshot", "as_of": "2026-08"}]
        gold["keypoints"][1]["registry"] = {"office": "registrar", "need": "who"}
        write(q / "gold.json", gold)
        c = q / e["dir"]
        pred = json.loads((c / "prediction.json").read_text(encoding="utf-8"))
        pred["context"] = [{"message_index": 1, "role": "ToolMessage", "tool": "get_page_tool", "text": "get_page 取得\n" + context_text}]
        write(c / "prediction.json", pred)
        if funnel is not None:
            scores = json.loads((c / "scores.json").read_text(encoding="utf-8"))
            scores["funnel"] = funnel
            write(c / "scores.json", scores)
        return e

    FUNNEL = [{"id": "K1", "in_context": True, "in_context_source": "claude", "context_quote": "可以找到"},
              {"id": "K2", "in_context": False, "in_context_source": "claude"}]

    def test_a_reference_is_read_when_claude_says_its_keypoint_was_read_nothing_is_text_matched(self):
        with tempfile.TemporaryDirectory() as d:
            # the text the system read does NOT contain the gold quotes at all; only the funnel decides
            row = export_scores.build_row(self._question_with_refs(Path(d), "完全不同的文字", self.FUNNEL), Path(d))
        gr = {g["text"]: g for g in row["ground_truth"]["references"]}
        self.assertIs(gr["可以找到的原文"]["found"], True)
        self.assertIs(gr["讀不到的原文"]["found"], False)

    def test_without_a_funnel_the_references_are_not_judged(self):
        with tempfile.TemporaryDirectory() as d:
            row = export_scores.build_row(self._question_with_refs(Path(d), "前面 可以找到 的原文 後面"), Path(d))
        self.assertTrue(all(g["found"] is None for g in row["ground_truth"]["references"]))

    def test_the_row_carries_the_metrics_version(self):
        with tempfile.TemporaryDirectory() as d:
            e = make_question(Path(d))
            c = Path(d) / e["question"] / e["dir"]
            s = json.loads((c / "scores.json").read_text(encoding="utf-8"))
            s["metrics_version"] = "2026-11-15.context-recall-judged"
            write(c / "scores.json", s)
            row = export_scores.build_row(e, Path(d))
        self.assertEqual(row["metrics_version"], "2026-11-15.context-recall-judged")

    def test_prediction_and_ground_truth_references(self):
        with tempfile.TemporaryDirectory() as d:
            row = export_scores.build_row(self._question_with_refs(Path(d), "前面 可以找到 的原文 後面"), Path(d))
        pr = row["prediction"]["references"]
        self.assertEqual((len(pr), pr[0]["tool"], pr[0]["index"]), (1, "get_page_tool", 1))
        self.assertIn("可以找到", pr[0]["text"])
        gr = {g["text"]: g for g in row["ground_truth"]["references"]}
        self.assertEqual(len(gr), 2)                                   # 同一句的快照與現場合併成一條
        self.assertEqual([s["kind"] for s in gr["可以找到的原文"]["sources"]], ["snapshot", "live"])
        self.assertEqual(gr["可以找到的原文"]["keypoints"], ["K1"])

    def test_registry_alternatives_for_who_floor_form_link(self):
        import registry_lib
        reg = registry_lib.load()
        who = export_scores.registry_alternatives({"office": "registrar", "need": "who"}, reg)
        self.assertEqual(len(who["items"]), len(registry_lib.office(reg, "registrar")["staff"]))
        self.assertTrue(any("63273" in x for x in who["items"]))
        floor = export_scores.registry_alternatives({"office": "registrar", "need": "floor"}, reg)
        self.assertIn("四樓", floor["items"][0])
        link = export_scores.registry_alternatives({"need": "form_link", "form": "QP-T01-04-21"}, reg)
        self.assertTrue(link["items"][0].endswith("QP-T01-04-21"))
        self.assertIsNone(export_scores.registry_alternatives({"office": "nope", "need": "who"}, reg))

    def test_hard_keypoint_keeps_its_acceptable_expressions(self):
        with tempfile.TemporaryDirectory() as d:
            e = make_question(Path(d))
            q = Path(d) / e["question"]
            gold = json.loads((q / "gold.json").read_text(encoding="utf-8"))
            gold["keypoints"][0]["acceptable_expressions"] = ["25學分", "二十五學分"]
            write(q / "gold.json", gold)
            row = export_scores.build_row(e, Path(d))
        self.assertEqual(row["ground_truth"]["keypoints"][0]["acceptable_expressions"], ["25學分", "二十五學分"])
        self.assertIsNone(row["ground_truth"]["keypoints"][0]["alternatives"])

    def test_ground_truth_answer_segments(self):
        """reference_answer 展開成片段：可替換的帶全部可接受的寫法與規則，不可替換、選答各有類型；沒有 reference_answer 時是 None。"""
        import registry_lib
        reg = registry_lib.load()
        gold = {"reference_answer": "註冊組在 {{固定|行政大樓四樓}}，聯絡 {{可替換:K1|王揚忠（組長）分機 63273}}。{{選答}}\n第二行",
                "keypoints": [{"id": "K1", "text": "要寫註冊組聯絡人", "kind": "hard", "registry": {"office": "registrar", "need": "who"}}]}
        segs = export_scores.ground_truth_answer(gold, reg)
        self.assertEqual([x["t"] for x in segs], ["text", "fixed", "text", "rep", "text", "opt", "text"])
        rep = segs[3]
        self.assertEqual(len(rep["forms"]), len(registry_lib.office(reg, "registrar")["staff"]))
        self.assertIn("姓名須對上分機", rep["rule"])
        self.assertEqual("".join(x["v"] for x in segs if x["t"] == "text"), "註冊組在 ，聯絡 。\n第二行")
        self.assertIsNone(export_scores.ground_truth_answer({"keypoints": []}, reg))

    def test_cashier_reference_answer_and_extension_list(self):
        import registry_lib
        gold = json.loads((HERE.parent / "cashier_contact" / "gold.json").read_text(encoding="utf-8"))
        segs = export_scores.ground_truth_answer(gold, registry_lib.load())
        reps = [x for x in segs if x["t"] == "rep"]
        self.assertEqual([x["v"] for x in reps], ["62120", "劉桂芬（組長）分機 62120"])
        self.assertEqual([x["v"] for x in segs if x["t"] == "fixed"], ["(02) 2939-3091"])
        forms = {f.split("  ")[-1][:5]: f for f in reps[0]["forms"]}
        self.assertEqual(len(reps[0]["forms"]), 12)
        self.assertIn("無人員對應", forms["62119"])                                   # 通知單列的線路，沒有人名，K3 不適用
        self.assertIn("待補", forms["62173"])
        self.assertIn("鄭雅玲", forms["62173"])


class TestPreviewExport(unittest.TestCase):
    """11 題的預覽案例（真實檔案）：每題一行、題號 1–11、第 1 題是真實 run、其餘是假設答案、階段 3 的值都有。"""

    def test_eleven_rows(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "preview.jsonl"
            rows = export_scores.export(export_scores.DEFAULT_CASES, out)
            lines = out.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 11)
        self.assertEqual([r["query"]["query_id"] for r in rows], list(range(1, 12)))
        self.assertEqual([r["source"] for r in rows], ["real"] + ["hypothetical"] * 10)
        self.assertEqual([r["group"] for r in rows], ["Factual Questions"] * 3 + ["Cross-Office Procedural Questions"] * 8)
        for r in rows:
            self.assertIsNotNone(r["completeness"], r["question"])
            self.assertIsNotNone(r["evidence"], r["question"])
            json.loads(lines[r["query"]["query_id"] - 1])           # 每一行都是合法 JSON


if __name__ == "__main__":
    unittest.main()
