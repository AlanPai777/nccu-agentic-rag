"""
evaluation/compare_tests.py

比對「隔離回推的結果」與「預期鑰匙」：改壞的答案裡植入了哪些錯誤與對照，子代理的 trace.json 抓到了幾個、
有沒有把對照組誤判。離線，不呼叫任何 LLM。

用法（在專案根目錄）：
  python evaluation/compare_tests.py evaluation/cashier_contact/tests/tampered_v1
  python evaluation/compare_tests.py evaluation/cashier_contact/tests/tampered_v1 --run run2
  python evaluation/compare_tests.py <test_dir> --json

<test_dir> 需要有：
  expected.json              鑰匙：每個 item 有 id、kind、expected（supported | unsupported）、line（答案裡的一整行）、ambiguous
  trace_input.json           子代理當時拿到的輸入（用來取得 answer_text 與驗證引文）
  results/<run>/trace.json   子代理的輸出（預設 run1）

比對規則（鑰匙裡的 how_to_read 有同樣的說明）：
  - 落在某個 item 的 line 裡的主張，都屬於這個 item（以主張在答案裡的位置判斷，同一段文字出現多次也不會錯配）。
  - expected = unsupported：這一行至少有一個主張被標 unsupported 就算抓到（錯誤有被標出來）。
  - expected = supported：這一行至少要有一個主張，而且全部都是 supported。
  - ambiguous = true 的項目，結果與預期不同時列為 REVIEW（需人工確認），不算失敗。
  - 結束碼：0 ＝ 沒有失敗（可以有 REVIEW）；1 ＝ 有失敗；2 ＝ 檔案缺漏。
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from stage3 import check_trace  # noqa: E402


def compare(test_dir: Path, run: str = "run1") -> dict:
    exp = json.loads((test_dir / "expected.json").read_text(encoding="utf-8"))
    ti = json.loads((test_dir / "trace_input.json").read_text(encoding="utf-8"))
    tr = json.loads((test_dir / "results" / run / "trace.json").read_text(encoding="utf-8"))
    checked = check_trace(ti, tr)
    answer = ti["answer_text"]
    claims = [c for c in checked["claims"] if c["span_verified"]]

    ranges = {}
    for it in exp["items"]:
        i = answer.find(it["line"])
        ranges[it["id"]] = (i, i + len(it["line"])) if i != -1 else None

    def belongs(c, rng):
        if rng is None:
            return False
        pos = c.get("span_pos")
        if pos:
            return rng[0] <= pos[0] and pos[1] <= rng[1]
        return c["answer_span"] in answer[rng[0]:rng[1]]      # 只有正規化後才找得到，位置未知

    rows, used = [], set()
    for it in exp["items"]:
        rng = ranges[it["id"]]
        mine = [c for c in claims if belongs(c, rng)]
        used |= {c["id"] for c in mine}
        status = [(c["id"], c["status_checked"]) for c in mine]
        if rng is None:
            result, why = "FAIL", "鑰匙的 line 不在 answer_text 裡（鑰匙與輸入不一致）"
        elif not mine:
            result, why = "FAIL", "這一行沒有任何主張（沒有涵蓋）"
        elif it["expected"] == "unsupported":
            ok = any(s != "supported" for _, s in status)
            result, why = ("PASS", "錯誤被標出來") if ok else ("FAIL", "有錯誤的一行，卻全部被標 supported")
        else:
            ok = all(s == "supported" for _, s in status)
            result, why = ("PASS", "全部 supported") if ok else ("FAIL", "對照組被誤判為 unsupported")
        if result == "FAIL" and it.get("ambiguous"):
            result = "REVIEW"
        rows.append({"id": it["id"], "kind": it["kind"], "expected": it["expected"], "ambiguous": it.get("ambiguous", False),
                     "claims": status, "result": result, "why": why})

    unattributed = [(c["id"], c["answer_span"], c["status_checked"]) for c in claims if c["id"] not in used]
    planted = [r for r in rows if r["expected"] == "unsupported"]
    controls = [r for r in rows if r["expected"] == "supported"]
    return {
        "version": exp.get("version"), "run": run, "rows": rows,
        "caught": sum(r["result"] == "PASS" for r in planted), "planted": len(planted),
        "controls_ok": sum(r["result"] == "PASS" for r in controls), "controls": len(controls),
        "review": [r["id"] for r in rows if r["result"] == "REVIEW"],
        "failed": [r["id"] for r in rows if r["result"] == "FAIL"],
        "claims_total": len(checked["claims"]), "claims_counted": sum(1 for c in claims if c.get("counted", True)),
        "unattributed_claims": unattributed, "check_warnings": checked["warnings"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("test_dir")
    ap.add_argument("--run", default="run1")
    ap.add_argument("--json", dest="json_out", action="store_true")
    args = ap.parse_args()
    d = Path(args.test_dir)
    need = [d / "expected.json", d / "trace_input.json", d / "results" / args.run / "trace.json"]
    missing = [str(p) for p in need if not p.exists()]
    if missing:
        print("缺檔：", *missing, sep="\n  ", file=sys.stderr)
        return 2
    r = compare(d, args.run)
    if args.json_out:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"{r['version']}  {r['run']}：主張 {r['claims_total']} 個（計入 {r['claims_counted']}）")
        for x in r["rows"]:
            cl = " ".join(f"{cid}:{st[:3]}" for cid, st in x["claims"]) or "—"
            print(f"  {x['id']} {x['kind']:13s} 預期 {x['expected']:11s} 主張 [{cl}]  {x['result']:6s} {x['why']}" + ("（ambiguous）" if x["ambiguous"] else ""))
        print(f"\n植入的錯誤抓到 {r['caught']}/{r['planted']}；對照組沒有被誤判 {r['controls_ok']}/{r['controls']}"
              + (f"；需人工確認 {r['review']}" if r["review"] else "") + (f"；失敗 {r['failed']}" if r["failed"] else ""))
        if r["unattributed_claims"]:
            print("不屬於任何項目的主張：", r["unattributed_claims"])
        for w in r["check_warnings"]:
            print("check 警告：", w)
    return 1 if r["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
