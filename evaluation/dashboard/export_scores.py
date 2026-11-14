"""
evaluation/dashboard/export_scores.py

把各題的評測結果組成 dashboard 讀的 .jsonl（每題一行，WSM 的 RAG Evaluation Visualizer 的格式加上我們多出來的欄位）。
離線，不呼叫 LLM、不連網。輸入是每題一個資料夾：gold.json（題目資料夾）與 <dir>/ 裡的 scores.json、judge.json、trace.json、prediction.json。

用法（專案根目錄）：
  python evaluation/dashboard/export_scores.py                                    # 預覽：sample/preview_cases.json → sample/preview_hypothetical.jsonl
  python evaluation/dashboard/export_scores.py --cases my_cases.json --out my_run.jsonl

每一行的欄位（缺的值一律寫 null，頁面顯示灰色的「—」，不是 0）：
  query            {query_id: 數字, short: 簡短題名, content: 題目全文, query_type: gold 的 query_type（系統內部的分類）}
  group            分組標題（Factual Questions／Cross-Office Procedural Questions）
  source           "real"（真實 run）或 "hypothetical"（pipeline_setup 的假設答案）；頁面只在有 hypothetical 時才顯示橫幅
  case / question / run_id / system_version / label / model   這一行是哪個案例、哪個版本（紀錄用，頁面不標）
  ROUGELScore, Words_Precision, Words_Recall, Sentences_Precision, Sentences_Recall, completeness, hallucination, irrelevance   WSM 的欄位
  accuracy         {hit, total, value}        規則版
  keypoint         {precision, recall, f1}    事實單位（對 keypoint）
  claim            {precision, recall, f1, claims, correct}   答案單位（對主張）
  evidence         {rate, supported, claims, unsupported}     有依據的主張比例
  rouge            {p, r, f}
  context          {sentence: {p, r, f}, words: {p, r, f}}
  ground_truth     {content, answer: [{id, text, tag: replaceable|fixed|semantic, example, forms, rule}], keypoints: [...], references}
  prediction       {content}
  responses        {keypoints: [{id, text, verdict, reason, claims}], claims: [{id, answer_span, status, why}], funnel, warnings, disagreements, ungrounded}
  routing          {expected: gold 的 query_type, router: 系統當次判斷的類型（prediction 的 trace.query_type）}
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(EVAL / "registry"))
import registry_lib  # noqa: E402
import score_programmatic  # noqa: E402   與規則版、階段 3 用同一個比對（norm）
DEFAULT_CASES = HERE / "sample" / "preview_cases.json"
DEFAULT_OUT = HERE / "sample" / "preview_hypothetical.jsonl"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _source(case_dir: str) -> str:
    """runs/ 底下是真實 run，tests/pipeline_setup/ 底下是假設答案。"""
    return "real" if case_dir.replace("\\", "/").startswith("runs/") else "hypothetical"


def _num(d, *keys):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def registry_alternatives(spec: dict, reg: dict) -> dict | None:
    """登記表型 keypoint 的「替代寫法」：答案寫哪些都算對（聯絡人、樓層、連結、代表線）。"""
    need = spec.get("need")
    try:
        if need == "who":
            o = registry_lib.office(reg, spec["office"])
            items = [_staff_item(e) for e in o["staff"]]
            example = next((i for i, e in enumerate(o["staff"]) if e.get("status") == "both"), 0)    # 代表組：現場與快照都有的人員優先
            return {"summary": f"any one of {len(items)} registered staff of {o['name']}, with the matching extension", "items": items, "example": example}
        if need == "floor":
            o = registry_lib.office(reg, spec["office"])
            items = [" / ".join(f["accepted"]) for f in o["floors"] if not spec.get("unit") or spec["unit"] in f["units"]]
            return {"summary": f"{o['name']} floor", "items": items}
        if need == "form_link":
            f = next(x for x in reg["forms"] if x["id"] == spec["form"])
            return {"summary": f"form {f['id']} link", "items": [f["url"]]}
        if need == "line":
            o = registry_lib.office(reg, spec["office"])
            ln = next(x for x in o["lines"] if x.get("key") == spec.get("key"))
            return {"summary": f"{o['name']} line", "items": [f"{ln['kind']}  {ln['value']}"]}
    except (KeyError, StopIteration):
        return None
    return None


def _staff_item(e: dict) -> str:
    names = []
    for n in e["names"]:
        if n["value"] not in names:
            names.append(n["value"])
    titles = [t["value"] for t in e["titles"]]
    return " / ".join(names + [t for t in titles if t not in names]) + f"  {e['ext'] or '—'}"


def extension_alternatives(gold: dict) -> dict | None:
    """沒有用登記表、直接把允許分機寫在 gold 的題目（出納組電話）：人員與分機成對，沒有人名的號碼寫明原因。"""
    av = gold.get("allowed_values") or {}
    exts = av.get("extension") or []
    if not exts:
        return None
    by_ext = {p["extension"]: p for p in av.get("extension_by_person", [])}
    items, example = [], None
    for e in exts:
        p = by_ext.get(e["value"])
        text = f"{p['name']} / {p['title']}  {e['value']}" if p else str(e["value"])
        if e.get("short_note"):
            text += f"（{e['short_note']}）"
        elif not p:
            text += "（無人員對應）"
        items.append(text)
        if example is None and p and e.get("status") == "live_confirmed":
            example = len(items) - 1
    return {"summary": "", "items": items, "example": example if example is not None else 0}


def ground_truth_answer(gold: dict, reg: dict) -> list[dict]:
    """完整的標準答案：每個 keypoint 一行，並標明能不能換。
    replaceable：登記表人員或分機（任一組皆可，姓名須對上分機）；fixed：hard 且沒有替代組（數字、表單編號、連結、順序）；
    semantic：語意相符即可（淡灰小字，不另標）。"""
    out = []
    for k in gold.get("keypoints", []):
        alt = None
        if k.get("registry"):
            alt = registry_alternatives(k["registry"], reg)
            if alt and k["registry"].get("need") != "who":
                alt = None                       # 樓層、連結、代表線只是寫法不同，不是換人，不算「可替換」
        elif k.get("value_check") == "extension":
            alt = extension_alternatives(gold)
        if alt and len(alt["items"]) > 1:
            tag = "replaceable"
        elif k.get("kind") == "hard":
            tag, alt = "fixed", None
        else:
            tag, alt = "semantic", None
        line = {"id": k["id"], "text": k["text"], "tag": tag, "required": k.get("required"), "applies_if": k.get("applies_if")}
        if alt:
            ex = alt.get("example", 0)
            line.update(example=alt["items"][ex], forms=alt["items"], rule="姓名須對上分機，配錯即錯")
        out.append(line)
    return out


def _title(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:90]
    return ""


def build_row(entry: dict, root: Path = EVAL) -> dict:
    qdir = root / entry["question"]
    case = qdir / entry["dir"]
    gold = _read(qdir / "gold.json")
    if gold is None:
        raise FileNotFoundError(f"找不到 {qdir / 'gold.json'}")
    scores = _read(case / "scores.json") or _read(case / "scores.stage2.json")
    if scores is None:
        raise FileNotFoundError(f"找不到 {case} 的 scores.json 或 scores.stage2.json")
    pred = _read(case / "prediction.json") or {}
    judge = _read(case / "judge.json")
    trace = _read(case / "trace.json")

    ctx = scores.get("context") or {}
    kp = scores.get("keypoint")                 # 階段 3 才有
    fact = scores.get("fact_unit")
    claim = scores.get("claim_unit")
    ev = scores.get("evidence_support")
    acc = scores.get("accuracy_rule") or scores.get("accuracy") or {}
    rouge = scores.get("rouge_l")

    verdicts = {k["id"]: k for k in (judge or {}).get("keypoints", [])}
    gt_kps = gold.get("keypoints", [])
    reg = registry_lib.load()

    # 系統實際讀進來的內容（每項一筆）；counted 表示它算進 Retrieval 指標
    context = pred.get("context") or []
    counted, counted_idx = score_programmatic.counted_context(context) if context else ([], [])
    ctx_norm = score_programmatic.norm("\n".join(c["text"] for c in counted))
    pred_refs = [{"index": i + 1, "role": c.get("role"), "tool": c.get("tool"), "title": _title(c.get("text")), "chars": len(c.get("text") or ""),
                  "text": c.get("text"), "counted": i in counted_idx} for i, c in enumerate(context)]

    # gold 的原文出處：去重（同一句常被好幾個 keypoint 引用，快照與現場各一份）；found = 系統讀到的內容裡找得到
    gt_refs = {}
    for k in gt_kps:
        for r in k.get("references", []) or []:
            key = score_programmatic.norm(r["text"])
            e = gt_refs.setdefault(key, {"text": r["text"], "sources": [], "keypoints": [], "found": bool(key) and key in ctx_norm})
            src = {"kind": r.get("source_kind"), "as_of": r.get("as_of"), "url": r.get("source_url")}
            if src not in e["sources"]:
                e["sources"].append(src)
            if k["id"] not in e["keypoints"]:
                e["keypoints"].append(k["id"])
    claims = (trace or {}).get("claims", [])

    hard = acc.get("hard_keypoints")
    hit = acc.get("hit")
    row = {
        "language": "zh",
        "query": {"query_id": entry["id"], "short": entry["short"], "content": gold.get("query"), "query_type": gold.get("query_type")},
        "group": entry["group"],
        "source": _source(entry["dir"]),
        "case": case.name,
        "question": entry["question"],
        "run_id": scores.get("run_id") or pred.get("run_id"),
        "system_version": scores.get("system_version") or pred.get("system_version"),
        "label": pred.get("label"),
        "model": pred.get("model"),
        "ROUGELScore": _num(rouge, "f"),
        "Words_Precision": _num(ctx, "words", "p"),
        "Words_Recall": _num(ctx, "words", "r"),
        "Sentences_Precision": _num(ctx, "sentence", "p"),
        "Sentences_Recall": _num(ctx, "sentence", "r"),
        "completeness": _num(kp, "completeness"),
        "hallucination": _num(kp, "hallucination"),
        "irrelevance": _num(kp, "irrelevance"),
        "accuracy": {"hit": hit, "total": hard, "value": acc.get("accuracy")} if hard is not None else None,
        "keypoint": {"precision": fact["precision"], "recall": fact["recall"], "f1": fact["f1"]} if fact else None,
        "claim": ({"precision": claim["precision"], "recall": claim["recall"], "f1": claim["f1"],
                   "claims": claim.get("claims"), "correct": claim.get("correct_claims")} if claim else None),
        "evidence": ({"rate": ev["rate"], "supported": ev["supported"], "claims": ev["claims"], "unsupported": ev.get("unsupported_claims", [])}
                     if ev else None),
        "rouge": rouge,
        "context": {"sentence": ctx.get("sentence"), "words": ctx.get("words")} if ctx else None,
        "ground_truth": {"content": gold.get("content"),
                         "keypoints": [{"id": k["id"], "text": k["text"], "required": k.get("required"), "kind": k.get("kind"),
                                        "acceptable_expressions": k.get("acceptable_expressions") or [],
                                        "references": [{"text": r["text"], "source_kind": r.get("source_kind"), "as_of": r.get("as_of"),
                                                        "source_url": r.get("source_url")} for r in (k.get("references") or [])],
                                        "alternatives": registry_alternatives(k["registry"], reg) if k.get("registry") else None,
                                        "applies_if": k.get("applies_if")} for k in gt_kps],
                         "answer": ground_truth_answer(gold, reg),
                         "references": list(gt_refs.values())},
        "prediction": {"content": pred.get("answer_body"), "references": pred_refs},
        "responses": {
            "keypoints": [{"id": k["id"], "text": k["text"], "verdict": verdicts.get(k["id"], {}).get("verdict"),
                           "reason": verdicts.get(k["id"], {}).get("reason"), "claims": verdicts.get(k["id"], {}).get("claims", [])} for k in gt_kps]
            if judge else None,
            "claims": [{"id": c["id"], "answer_span": c.get("answer_span"), "status": c.get("status"), "why": c.get("why")} for c in claims] if trace else None,
            "funnel": scores.get("funnel"),
            "warnings": scores.get("warnings", []),
            "disagreements": scores.get("disagreements", []),
            "ungrounded": scores.get("ungrounded_correct_keypoints", []),
        },
        "routing": {"expected": gold.get("query_type"), "router": (pred.get("trace") or {}).get("query_type")},
    }
    return row


def export(cases_path: Path, out_path: Path, root: Path = EVAL) -> list[dict]:
    spec = json.loads(cases_path.read_text(encoding="utf-8"))
    rows = [build_row(e, root) for e in spec["cases"]]
    ids = [r["query"]["query_id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError(f"query_id 重複：{ids}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args()
    rows = export(a.cases, a.out)
    for r in rows:
        k = r["keypoint"]
        print(f"Q{r['query']['query_id']:<2d} {r['query']['short']:<10s} {r['source']:<12s} {r['case']:<12s} "
              f"C={r['completeness'] if r['completeness'] is not None else '—'}  H={r['hallucination'] if r['hallucination'] is not None else '—'}  "
              f"router={r['routing']['router']} (expected {r['routing']['expected']})")
    n_h = sum(r["source"] == "hypothetical" for r in rows)
    print(f"→ {a.out}（{len(rows)} 題；real {len(rows) - n_h}、hypothetical {n_h}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
