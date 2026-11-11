"""
evaluation/course_limit/tests/pipeline_setup/make_runs.py

流程測試用：把 answers/*.txt 的「假設答案」組成 prediction.json，讓整條評測管線（階段 2、階段 3、隔離回推、Keypoint 判斷）
假裝跑一次。**這不是系統的真實答案，分數不能當評測結果**（plan/phase_k_evaluation_design.md 的 13.5）。

- answer_raw：answers/<名>.txt 的內容，加上「來源：」行與【資料狀態】段（模仿系統答案的形狀，評分前會被剝掉）
- context：不編造內容；用 sources/snapshot/ 裡真實的頁面原文，包成 get_page 工具輸出的樣子（標頭、ledger 標記行、頁面原文）
- model／system_version／label 明確標示假設；不放 runs/，所以 list_runs.py 與之後的彙整都讀不到

用法（專案根目錄）：
  python evaluation/course_limit/tests/pipeline_setup/make_runs.py
已存在的案例資料夾不覆蓋（避免新舊檔案混在一起），要重做請先自己刪掉那個資料夾。
"""
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COURSE = HERE.parents[1]                    # evaluation/course_limit
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evaluation"))
import run_system  # noqa: E402  (設好 LIVE_BROWSER=off 等環境變數)
from rag.live.ledger import DISCLOSURE_HEADER, make_marker  # noqa: E402

# 系統「讀到」的頁面（快照複本檔名，網址）。順序模仿一次搜尋後依序 get_page。
PAGES = [
    ("aca_faq_course_selection.txt", "https://aca.nccu.edu.tw/zh/常用連結/教務處qa/選課業務"),
    ("aca_law01A.txt", "https://aca.nccu.edu.tw/download/rulesdata/law01A.pdf"),
    ("aca_course_notice_11407.txt", "https://aca.nccu.edu.tw/download/course/選課須知11407.pdf"),
]
CASES = ["complete", "partial", "wrong"]
LABEL = "假設答案，流程測試，不計分"
MODEL = "hypothetical（Claude Code 撰寫，不是系統輸出）"
BODY_MARK = "# 以下為該筆記錄的 text 欄位全文（逐字複本）"


def snapshot_body(fname: str) -> str:
    raw = (COURSE / "sources" / "snapshot" / fname).read_text(encoding="utf-8")
    return raw.split(BODY_MARK, 1)[1].strip()


def build_context() -> list[dict]:
    context = []
    for i, (fname, url) in enumerate(PAGES):
        text = snapshot_body(fname)
        marker = make_marker(url, status="snapshot", checked="", snap="2026-08")
        header = f"get_page 取得 {len(text)} 字，標題: {fname}，subdomain: aca\n{marker}"
        context.append({"message_index": 2 * i + 1, "role": "ToolMessage", "tool": "get_page_tool", "text": f"{header}\n{text}"})
    return context


def answer_raw(body: str) -> str:
    urls = [u for _, u in PAGES]
    src = "來源：" + urls[0] + "\n" + "\n".join(f"- {u}" for u in urls[1:])
    footer = f"{DISCLOSURE_HEADER}\n- 使用資料庫（快照）：{len(urls)} 頁\n" + "\n".join(f"  - {u}" for u in urls)
    return f"{body.strip()}\n\n{src}\n\n---\n{footer}"


def main() -> int:
    gold = json.loads((COURSE / "gold.json").read_text(encoding="utf-8"))
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    made = []
    for name in CASES:
        out_dir = HERE / name
        if out_dir.exists():
            print(f"已存在，不覆蓋：{out_dir.relative_to(ROOT)}", file=sys.stderr)
            return 1
    for name in CASES:
        raw = answer_raw((HERE / "answers" / f"{name}.txt").read_text(encoding="utf-8"))
        body, stripped = run_system.split_answer(raw)
        pred = {
            "query_id": gold["query_id"], "query": gold["query"], "run_id": name, "label": LABEL,
            "started_at": now, "finished_at": now, "system_version": "hypothetical", "model": MODEL,
            "live": False, "live_fetch_env": None,
            "answer_raw": raw, "answer_body": body, "stripped": stripped,
            "context": build_context(), "checks": {"contact_pages": [], "contact_consistency": []},
            "trace": {"query_type": "knowledge", "turn": 1, "self_eval_note": None, "subdomain_hint": "aca", "tool_calls": []},
        }
        out_dir = HERE / name
        out_dir.mkdir()
        (out_dir / "prediction.json").write_text(json.dumps(pred, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        made.append((name, len(body)))
    for name, n in made:
        print(f"已寫入 {(HERE / name / 'prediction.json').relative_to(ROOT)}（答案正文 {n} 字）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
