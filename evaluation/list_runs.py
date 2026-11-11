#!/usr/bin/env python3
"""
evaluation/list_runs.py

列出一題的所有 run（唯讀，離線，不呼叫 LLM、不上網）。路徑不帶資訊，要看每次 run 是什麼就看這張表。

  python evaluation/list_runs.py evaluation/cashier_contact          # 題目資料夾（裡面有 runs/）
  python evaluation/list_runs.py evaluation/cashier_contact/runs     # 也可以直接給 runs/
  python evaluation/list_runs.py evaluation/cashier_contact --json
  python evaluation/list_runs.py --sample

欄位：run、標籤、開始時間、模型、系統版本、階段 2（有 scores.stage2.json）、階段 3（有 scores.json）、
Keypoint 完整度（Relevant ÷ K）、有依據比例（evidence-support rate）。沒有的欄位印 "-"。
結束碼：0 = 有列出；2 = 找不到 runs 資料夾或裡面沒有 run。
"""
import argparse
import json
import sys
from pathlib import Path


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def collect(runs_dir: Path) -> list[dict]:
    rows = []
    for d in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        pred = _load(d / "prediction.json")
        if pred is None:
            continue
        scores = _load(d / "scores.json")
        rows.append({
            "folder": d.name,
            "run_id": pred.get("run_id"),
            "label": pred.get("label", ""),
            "started_at": pred.get("started_at"),
            "model": pred.get("model"),
            "system_version": pred.get("system_version"),
            "stage2": (d / "scores.stage2.json").exists(),
            "stage3": scores is not None,
            "completeness": (scores or {}).get("keypoint", {}).get("completeness"),
            "support_rate": (scores or {}).get("evidence_support", {}).get("rate"),
            "id_matches_folder": pred.get("run_id") == d.name,
        })
    return rows


def _fmt(v) -> str:
    if v is None or v == "":
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}"
    if isinstance(v, bool):
        return "有" if v else "-"
    return str(v)


def render(rows: list[dict]) -> str:
    head = ["run", "標籤", "開始時間", "模型", "系統版本", "階段2", "階段3", "完整度", "有依據"]
    lines = [head]
    for r in rows:
        name = r["folder"] + ("" if r["id_matches_folder"] else "（run_id 與資料夾名不同）")
        lines.append([name, _fmt(r["label"]), _fmt(r["started_at"]), _fmt(r["model"]), _fmt(r["system_version"]),
                      _fmt(r["stage2"]), _fmt(r["stage3"]), _fmt(r["completeness"]), _fmt(r["support_rate"])])
    widths = [max(len(row[i]) for row in lines) for i in range(len(head))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in lines)


SAMPLE = [{"folder": "run01", "run_id": "run01", "label": "修正前，試做", "started_at": "2026-11-09T23:42:25+08:00",
           "model": "gemma4:31b-cloud", "system_version": "abc1234", "stage2": True, "stage3": True,
           "completeness": 1.0, "support_rate": 1.0, "id_matches_folder": True}]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="題目資料夾（裡面有 runs/）或 runs/ 本身")
    ap.add_argument("--json", dest="json_out", action="store_true")
    ap.add_argument("--sample", action="store_true", help="印一筆範例輸出後結束")
    args = ap.parse_args()
    if args.sample:
        print(json.dumps(SAMPLE, ensure_ascii=False, indent=2) if args.json_out else render(SAMPLE))
        return 0
    if not args.path:
        ap.error("path is required")
    p = Path(args.path)
    runs_dir = p if p.name == "runs" else p / "runs"
    if not runs_dir.is_dir():
        print(f"找不到 runs 資料夾：{runs_dir}", file=sys.stderr)
        return 2
    rows = collect(runs_dir)
    if not rows:
        print(f"{runs_dir} 裡沒有 run（要有 prediction.json 的子資料夾）", file=sys.stderr)
        return 2
    print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json_out else render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
