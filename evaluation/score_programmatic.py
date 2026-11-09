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

ROOT = Path(__file__).resolve().parents[1]

# 這些 HumanMessage 是節點給 LLM 的指示，不是檢索到的資料，不算進 Context
_NODE_PROMPT_PREFIXES = ("這一輪系統建議的搜尋方向", "候選subdomain")
_EXT_RE = re.compile(r"(?<!\d)\d{5}(?!\d)")          # 分機：獨立的 5 位數（前後不是數字）
_PAIR_WINDOW = 12                                    # 人名後多少字內的第一個分機視為這個人的


def norm(s: str) -> str:
    """比對用正規化：NFKC、去掉所有空白與表格線（與 build_gold.py 驗證引句時相同）。"""
    return re.sub(r"[\s|]+", "", unicodedata.normalize("NFKC", s or ""))


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

    n_kp = len(keypoints) or 1
    covered = sum(1 for k in per_kp if k["in_context"])
    s_recall = covered / n_kp                                   # keypoint 層級
    s_precision = matched_chars / len(ctx_norm) if ctx_norm else 0.0   # 字數，WSM EIR 做法
    common = gold_words & ctx_words
    w_precision = len(common) / len(ctx_words) if ctx_words else 0.0
    w_recall = len(common) / len(gold_words) if gold_words else 0.0
    scores = {
        "counted_context_indices": used_idx,
        "context_chars": len(ctx_norm),
        "sentence": {"p": round(s_precision, 4), "r": round(s_recall, 4), "f": round(prf(s_precision, s_recall), 4)},
        "words": {"p": round(w_precision, 4), "r": round(w_recall, 4), "f": round(prf(w_precision, w_recall), 4)},
        "note": "Precision 與 F1 只供跨 run 比較（讀整頁，分母很大）；Recall 為 keypoint 層級（命中任一可接受原文即算讀到）",
    }
    return scores, per_kp


# --- Accuracy（規則）-------------------------------------------------------
def extract_extensions(text: str) -> list[str]:
    return _EXT_RE.findall(unicodedata.normalize("NFKC", text or ""))


def pair_mismatches(answer: str, people: list[dict]) -> list[dict]:
    """答案中「人名 後面緊接的分機」若與 extension_by_person 不符，就是配對錯誤。
    只在答案同時寫了人名與分機時檢查；人名後 _PAIR_WINDOW 字內沒有分機就略過。"""
    text = unicodedata.normalize("NFKC", answer or "")
    bad = []
    for p in people:
        name = p["name"]
        if not re.fullmatch(r"[一-鿿]{2,5}", name):      # 含罕用字拆寫（如 王(禾+翟)媗）的略過
            continue
        for m in re.finditer(re.escape(name), text):
            tail = text[m.end(): m.end() + _PAIR_WINDOW + 20]
            ext = _EXT_RE.search(tail)
            if ext and ext.start() <= _PAIR_WINDOW + 8 and ext.group() != p["extension"]:
                bad.append({"name": name, "said": ext.group(), "expected": p["extension"]})
    return bad


def accuracy(gold: dict, answer: str, context: list[dict]) -> tuple[dict, list[dict]]:
    ans_norm = norm(answer)
    av = gold.get("allowed_values", {})
    allowed = {e["value"] for e in av.get("extension", [])}
    disallowed = {d["value"]: d["reason"] for d in av.get("disallowed", [])}
    people = av.get("extension_by_person", [])

    per_kp, hard_total, hard_hit = [], 0, 0
    for kp in gold["keypoints"]:
        row = {"id": kp["id"], "kind": kp.get("kind", "hard")}
        if kp.get("kind", "hard") != "hard":
            row.update(verdict="needs_llm", note="語意事實，規則版不判斷，交給階段 3 的 Keypoint 判斷")
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
            wrong["unknown_values"] = unknown
            wrong["pair_mismatches"] = pair_mismatches(answer, people)
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
        "rule": "答案命中任一 acceptable_expressions，且沒有錯誤值或錯誤配對，才算 hit",
    }, per_kp


# --- 聯絡人題的漏斗：頁面 → 清單 → 答案 ---------------------------------------
def contact_funnel(gold: dict, answer: str, context: list[dict]) -> list[dict]:
    """聯絡人題每個 hard keypoint 的三步：人員頁原文 → contact_node 整理的清單 → 最終答案。
    用 acceptable_expressions 判斷這個值有沒有出現在各步，所以「頁面有、清單沒有」代表卡在解析
    （例如總機 (02)2939-3091 在頁尾，清單的格式沒有放它的位置），不是檢索或綜合的問題。"""
    if gold.get("query_type") != "contact":
        return []
    page_txt = norm("\n".join(c["text"] for c in context if c.get("kind") == "contact_page"))
    list_txt = norm("\n".join(c["text"] for c in context if c.get("kind") == "contact_list"))
    ans_txt = norm(answer)
    rows = []
    for kp in gold["keypoints"]:
        if kp.get("kind", "hard") != "hard":
            continue
        expr = [(e, norm(e)) for e in kp.get("acceptable_expressions", []) if norm(e)]
        in_page = [e for e, n in expr if n in page_txt]
        in_list = [e for e, n in expr if n in list_txt]
        in_ans = [e for e, n in expr if n in ans_txt]
        stage = ("頁面沒有" if not in_page else "解析丟失" if not in_list else "綜合沒寫" if not in_ans else "答案有")
        rows.append({
            "keypoint": kp["id"],
            "page_has_value": bool(in_page),
            "list_has_value": bool(in_list),
            "answer_has_value": bool(in_ans),
            "values_in_page": in_page,
            "values_in_list": in_list,
            "values_in_answer": in_ans,
            "stage": stage,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gold")
    ap.add_argument("prediction")
    args = ap.parse_args()

    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    pred_path = Path(args.prediction).resolve()
    pred = json.loads(pred_path.read_text(encoding="utf-8"))
    answer = pred["answer_body"]

    rouge = rouge_l(answer, gold["content"])
    acc, acc_kp = accuracy(gold, answer, pred["context"])
    ctx, ctx_kp = context_scores(gold["keypoints"], pred["context"])
    funnel_contact = contact_funnel(gold, answer, pred["context"])

    # 每個 keypoint 的漏斗前半（階段 3 之後再補「被答案用到」與「說對了」）
    funnel = []
    acc_by_id = {k["id"]: k for k in acc_kp}
    for k in ctx_kp:
        funnel.append({"id": k["id"], "in_context": k["in_context"],
                       "matched_reference": k["matched_reference"],
                       "rule_verdict": acc_by_id[k["id"]]["verdict"]})

    out = {
        "query_id": gold["query_id"],
        "run_id": pred["run_id"],
        "gold_data_as_of": gold.get("data_as_of"),
        "system_version": pred.get("system_version"),
        "rouge_l": rouge,
        "accuracy": acc,
        "context": ctx,
        "keypoints": {"accuracy_rule": acc_kp, "funnel_stage2": funnel, "contact_funnel": funnel_contact},
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
    print(f"Context 句子    P={ctx['sentence']['p']:.3f}  R={ctx['sentence']['r']:.2f}  F={ctx['sentence']['f']:.3f}   （P、F 只供比較）")
    print(f"Context 詞      P={ctx['words']['p']:.3f}  R={ctx['words']['r']:.2f}  F={ctx['words']['f']:.3f}")
    for f in funnel_contact:
        print(f"聯絡人漏斗 {f['keypoint']}：頁面 {'✔' if f['page_has_value'] else '✘'} → "
              f"清單 {'✔' if f['list_has_value'] else '✘'} → 答案 {'✔' if f['answer_has_value'] else '✘'}   【{f['stage']}】")
    print(f"\n已寫入 {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
