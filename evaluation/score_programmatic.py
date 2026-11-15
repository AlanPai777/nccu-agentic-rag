"""
evaluation/score_programmatic.py

評測階段 2（plan/phase_k_evaluation_design.md 第 4 節）：程式計算，不用 LLM、不上網。

  - ROUGE-L（answer_body vs gold content；jieba 切詞 + rouge_chinese，與 WSM rageval 同做法；記 P/R/F）
  - Accuracy（規則）：每個 hard keypoint 命中 acceptable_expressions 才算對；有 value_check 的
    keypoint 另檢查答案中的分機值（必須在 allowed_values、人名與分機成對）
  - Context 層 Sentence／Words P/R/F1：gold references vs 系統讀進來的內容（只供跨 run 比較 P、F1）
  - 每個 keypoint 的漏斗前半（讀進 context？）與聯絡人題的三步（頁面 → 清單 → 答案）

階段 3（Claude Code 的回推與 Keypoint 判斷）不在這裡。

用法（在專案根目錄）：
  python evaluation/score_programmatic.py evaluation/cashier_contact/gold.json \
      evaluation/cashier_contact/runs/<run_id>/prediction.json
輸出：同資料夾的 scores.stage2.json，並印出摘要。
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

# 指標定義的版本。2026-11-15：Context 的「有沒有讀到」不再用 gold 引用的逐字比對，改由 Claude 判斷（階段 3 的 judge.json），
# Sentence Recall 因此改成 Claude 判斷的結果（分母含引用登記表的 keypoint）；Sentence Precision 與 Words 指標仍是字串比對的機械指標，
# 只供跨 run 比較。這個版本以前（含 run01～run03 的舊算法）的 Context Sentence Recall／F1 不能與之後的直接比較。
# 2026-11-15（第二次）：gold 的 keypoint 可以標 `excluded`（議題 F39：定義不夠明確，先不計分）。標了的不進任何分母（Completeness、Hallucination、
# Irrelevance、Context Recall、規則版 Accuracy、Words／Sentence 字串比對），判定照舊保留，scores.json 另列被排除的項目與理由。沒有標 excluded 的題目，
# 數字與前一版逐位元相同；有標的題目與前一版不能直接比較。
METRICS_VERSION = "2026-11-15.excluded-keypoints"
METRICS_NOTE = ("Context Sentence Recall 由 Claude 判斷（階段 3；答對且有依據的 keypoint 直接算讀到），不是字串比對；分母含引用登記表的 keypoint。"
                "Sentence Precision 與 Words 指標是字串比對的機械指標，只供跨 run 比較；Sentence F1 混用兩者。"
                "此版本之前的 Context Sentence Recall／F1 不能與之後的直接比較。"
                "gold 標了 excluded 的 keypoint 不計入任何分母。")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent / "registry"))
import registry_lib  # noqa: E402


def _shown(p) -> str:
    """給人看的路徑：在專案裡印相對路徑，在專案外（例如測試的暫存資料夾）印完整路徑。"""
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)

# 這些 HumanMessage 是節點給 LLM 的指示，不是檢索到的資料，不算進 Context
_NODE_PROMPT_PREFIXES = ("這一輪系統建議的搜尋方向", "候選subdomain")
_EXT_RE = re.compile(r"(?<!\d)\d{5,6}(?!\d)")        # 分機：獨立的 5 或 6 位數（前後不是數字；營繕組技術人員是 6 位數）
_PAIR_WINDOW = 12                                    # 人名後多少字內的第一個分機視為這個人的


def norm(s: str) -> str:
    """比對用正規化：NFKC、去掉所有空白與表格線，以及私用區字元（U+E000–U+F8FF，表單簽核欄的字型符號，肉眼看不到，不算內容）。
    與 gold_check.py、build_gold.py 驗證引句時相同。"""
    return re.sub(r"[\s|\ue000-\uf8ff]+", "", unicodedata.normalize("NFKC", s or ""))


def prf(p: float, r: float) -> float:
    return 0.0 if (p + r) == 0 else 2 * p * r / (p + r)


# --- ROUGE-L -------------------------------------------------------------
def rouge_l(hyp: str, ref: str) -> dict:
    import jieba
    import rouge_chinese

    h = " ".join(jieba.cut(hyp or ""))
    r = " ".join(jieba.cut(ref or ""))
    if not h.strip() or not r.strip():
        return {"p": 0.0, "r": 0.0, "f": 0.0}
    try:
        s = rouge_chinese.Rouge().get_scores(h, r)[0]["rouge-l"]
    except ValueError:
        return {"p": 0.0, "r": 0.0, "f": 0.0}
    return {"p": round(s["p"], 4), "r": round(s["r"], 4), "f": round(s["f"], 4)}


# --- Context ---------------------------------------------------------------
def counted_context(context: list[dict]) -> tuple[list[dict], list[int]]:
    """哪些 context 項目算「系統讀進來的資料」：工具輸出、聯絡人頁面原文，以及節點注入的資料。
    排除：contact_list（整理過的清單，聯絡人題改用 contact_page 的原文）與節點給 LLM 的指示。"""
    kept = []
    for i, c in enumerate(context):
        if c.get("kind") == "contact_list":
            continue
        if c["role"] == "HumanMessage" and c["text"].startswith(_NODE_PROMPT_PREFIXES):
            continue
        kept.append((i, c))
    return [c for _, c in kept], [i for i, _ in kept]


def _words(text: str) -> list[str]:
    import jieba
    return [w for w in jieba.cut(text) if w.strip()]          # 與 WSM split_words 相同：只去掉空白詞


def context_scores(keypoints: list[dict], context: list[dict]) -> tuple[dict, list[dict]]:
    items, used_idx = counted_context(context)
    ctx_text = "\n".join(c["text"] for c in items)
    ctx_norm = norm(ctx_text)
    ctx_words = set(_words(ctx_text))

    per_kp, matched_chars, gold_words = [], 0, set()
    for kp in keypoints:
        if kp.get("excluded"):
            per_kp.append({"id": kp["id"], "in_context": None, "matched_reference": None, "n_references": 0,
                           "note": "gold 標了 excluded，不計入"})
            continue
        if kp.get("registry"):
            # 引用登記表的 keypoint 沒有自己的 references，不算進 Context 的 recall 分母（登記表的來源另外驗證）
            per_kp.append({"id": kp["id"], "in_context": None, "matched_reference": None, "n_references": 0,
                           "note": "引用登記表，不計入 Context recall"})
            continue
        refs = [r["text"] for r in kp.get("references", [])]
        found = [r for r in refs if norm(r) and norm(r) in ctx_norm]
        # 一個 keypoint 的 references 是「可接受的替代原文」：命中任一條就算讀到了
        best = max(found, key=lambda r: len(norm(r))) if found else None
        per_kp.append({
            "id": kp["id"],
            "in_context": bool(found),
            "matched_reference": best,
            "n_references": len(refs),
        })
        if best:
            matched_chars += len(norm(best))
        # Words 的 gold 詞集合：每個 keypoint 取與 context 詞重疊最多的那條 reference
        if refs:
            def overlap(r):
                return len(set(_words(r)) & ctx_words)
            gold_words |= set(_words(max(refs, key=overlap)))

    s_precision = matched_chars / len(ctx_norm) if ctx_norm else 0.0   # 字數，WSM EIR 做法（字串比對；只供比較）
    common = gold_words & ctx_words
    w_precision = len(common) / len(ctx_words) if ctx_words else 0.0
    w_recall = len(common) / len(gold_words) if gold_words else 0.0
    scores = {
        "counted_context_indices": used_idx,
        "context_chars": len(ctx_norm),
        "sentence": {"p": round(s_precision, 4), "r": None, "f": None,
                     "note": "Recall 與 F1 要等階段 3 的 Claude 判斷（stage3.py score）才算；這裡只有字串比對的 Precision"},
        "words": {"p": round(w_precision, 4), "r": round(w_recall, 4), "f": round(prf(w_precision, w_recall), 4)},
        "string_match": [{"id": k["id"], "found": k["in_context"], "matched_reference": k["matched_reference"]} for k in per_kp],
        "note": "字串比對的機械指標（Sentence Precision、Words P／R／F1）只供跨 run 比較，不代表系統有沒有讀到；字串比對的逐項結果在 string_match，不用來判斷「有沒有讀到」。",
    }
    return scores, per_kp


# --- Accuracy（規則）-------------------------------------------------------
def extract_extensions(text: str) -> list[str]:
    return _EXT_RE.findall(unicodedata.normalize("NFKC", text or ""))


def check_pairs(answer: str, people: list[dict]) -> list[dict]:
    """答案中「人名 後面緊接的分機」與 extension_by_person 比對，回傳每一對：{name, said, expected, ok}。
    只在答案同時寫了人名與分機時才有結果；人名後 _PAIR_WINDOW 字內沒有分機的略過。"""
    text = unicodedata.normalize("NFKC", answer or "")
    out = []
    for p in people:
        name = p["name"]
        if not re.fullmatch(r"[一-鿿]{2,5}", name):      # 含罕用字拆寫（如 王(禾+翟)媗）的略過
            continue
        for m in re.finditer(re.escape(name), text):
            tail = text[m.end(): m.end() + _PAIR_WINDOW + 20]
            ext = _EXT_RE.search(tail)
            if ext and ext.start() <= _PAIR_WINDOW + 8:
                out.append({"name": name, "said": ext.group(), "expected": p["extension"], "ok": ext.group() == p["extension"]})
    return out


def pair_mismatches(answer: str, people: list[dict]) -> list[dict]:
    return [{k: v for k, v in c.items() if k != "ok"} for c in check_pairs(answer, people) if not c["ok"]]


_REG = None


def _registry() -> dict:
    global _REG
    if _REG is None:
        _REG = registry_lib.load()
    return _REG


def accuracy(gold: dict, answer: str, context: list[dict]) -> tuple[dict, list[dict]]:
    ans_norm = norm(answer)
    av = gold.get("allowed_values", {})
    allowed = {e["value"] for e in av.get("extension", [])}
    disallowed = {d["value"]: d["reason"] for d in av.get("disallowed", [])}
    people = av.get("extension_by_person", [])

    per_kp, hard_total, hard_hit = [], 0, 0
    for kp in gold["keypoints"]:
        row = {"id": kp["id"], "kind": kp.get("kind", "hard")}
        if kp.get("excluded"):
            row.update(verdict="excluded", note="gold 標了 excluded，不計入")
            per_kp.append(row)
            continue
        if kp.get("kind", "hard") != "hard":
            row.update(verdict="needs_llm", note="語意事實，規則版不判斷，交給階段 3 的 Keypoint 判斷")
            per_kp.append(row)
            continue
        if kp.get("registry"):
            # 引用登記表：單位的人員／樓層、表單連結；條件式的在答案沒提到時不適用、不計入
            reg = _registry()
            row.update(registry_lib.check_keypoint(kp, answer, reg))
            row["applies_if"] = kp.get("applies_if")
            if row["verdict"] != "not_applicable":
                hard_total += 1
                if row["verdict"] == "hit":
                    hard_hit += 1
            per_kp.append(row)
            continue
        if kp.get("value_check") == "extension_pairs":
            # 條件式 keypoint（2026-11-11）：答案列出承辦人的姓名與分機時才適用，每一對都要與人員頁相符
            row["applies_if"] = kp.get("applies_if")
            pairs = check_pairs(answer, people)
            row["pairs_checked"] = pairs
            if not pairs:
                row.update(verdict="not_applicable", note="答案沒有列出承辦人的姓名與分機，這個 keypoint 不適用，不計入")
                per_kp.append(row)
                continue
            hard_total += 1
            bad = [{k: v for k, v in c.items() if k != "ok"} for c in pairs if not c["ok"]]
            if bad:
                row.update(verdict="wrong", wrong={"pair_mismatches": bad})
            else:
                row["verdict"] = "hit"
                hard_hit += 1
            per_kp.append(row)
            continue
        hard_total += 1
        expr = [norm(e) for e in kp.get("acceptable_expressions", [])]
        said = [e for e in expr if e and e in ans_norm]
        wrong = {}
        if kp.get("value_check") == "extension":
            exts = extract_extensions(answer)
            row["extensions_in_answer"] = sorted(set(exts))
            unknown = sorted({e for e in exts if e not in allowed})
            wrong["disallowed"] = [{"value": e, "reason": disallowed[e]} for e in sorted(set(exts)) if e in disallowed]
            # 不在允許集合就算 Wrong；禁止值是其中已知會被誤用的特例。另列待人工確認（gold 可能漏了合法分機）
            wrong["unknown_values"] = unknown      # 人名與分機的配對另由 K3（extension_pairs）檢查，不再算在這個 keypoint
        has_wrong = any(wrong.values())
        if said and not has_wrong:
            row["verdict"] = "hit"
            hard_hit += 1
        elif has_wrong:
            row["verdict"] = "wrong"
        else:
            row["verdict"] = "miss"
        row["matched_expressions"] = said[:5]
        if wrong:
            row["wrong"] = wrong
            if wrong.get("unknown_values"):
                row["needs_human_review"] = "答案有不在允許集合的分機；若確認是合法分機，代表 gold 漏了"
        per_kp.append(row)

    return {
        "hard_keypoints": hard_total,
        "hit": hard_hit,
        "accuracy": round(hard_hit / hard_total, 4) if hard_total else None,
        "rule": "答案命中任一 acceptable_expressions，且沒有錯誤的分機值，才算 hit；條件式 keypoint 不適用時不計入",
    }, per_kp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gold")
    ap.add_argument("prediction")
    args = ap.parse_args()

    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    pred_path = Path(args.prediction).resolve()
    pred = json.loads(pred_path.read_text(encoding="utf-8"))
    # 答案正文一律從 answer_raw 重算（與階段 3 相同）：剝掉來源行、資料狀態、「——選擇原因：…」與粗體符號，
    # 舊的 prediction.json（還沒剝選擇原因）也能用
    from run_system import split_answer
    answer = split_answer(pred["answer_raw"])[0].replace("**", "")

    rouge = rouge_l(answer, gold["content"])
    acc, acc_kp = accuracy(gold, answer, pred["context"])
    ctx, ctx_kp = context_scores(gold["keypoints"], pred["context"])

    # 漏斗在階段 3 才完整（有沒有讀到、被答案用到、說對了）；這裡只留規則版的判定
    funnel = [{"id": k["id"], "rule_verdict": k["verdict"]} for k in acc_kp]

    out = {
        "query_id": gold["query_id"],
        "run_id": pred["run_id"],
        "gold_data_as_of": gold.get("data_as_of"),
        "system_version": pred.get("system_version"),
        "metrics_version": METRICS_VERSION,
        "rouge_l": rouge,
        "accuracy": acc,
        "context": ctx,
        "keypoints": {"accuracy_rule": acc_kp, "funnel_stage2": funnel},
    }
    out_path = pred_path.with_name("scores.stage2.json")
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"題目：{gold['query']}    run：{pred['run_id']}")
    print(f"\nROUGE-L        P={rouge['p']:.2f}  R={rouge['r']:.2f}  F={rouge['f']:.2f}")
    print(f"Accuracy       {acc['hit']}/{acc['hard_keypoints']} = {acc['accuracy']}")
    for k in acc_kp:
        extra = ""
        if k.get("wrong"):
            w = k["wrong"]
            extra = f"  wrong={ {a: b for a, b in w.items() if b} }"
        print(f"  {k['id']}: {k['verdict']}{extra}")
    print(f"Context 句子    P={ctx['sentence']['p']:.3f}（字串比對，只供比較）  R、F1：等階段 3 的 Claude 判斷")
    print(f"Context 詞      P={ctx['words']['p']:.3f}  R={ctx['words']['r']:.2f}  F={ctx['words']['f']:.3f}   （字串比對，只供比較）")
    print(f"\n已寫入 {_shown(out_path)}")


if __name__ == "__main__":
    sys.exit(main())
