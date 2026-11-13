"""
evaluation/leave_form_download/tests/pipeline_setup/make_runs.py

流程測試用：把 answers/*.txt 的「假設答案」組成 prediction.json，讓整條評測管線（階段 2、階段 3、隔離回推、Keypoint 判斷）
假裝跑一次。**這不是系統的真實答案，分數不能當評測結果**（plan/phase_k_evaluation_design.md 的 13.6）。

證據照「資源類題目」真實的形狀組（不編造內容，頁面與表單原文都是 output/ 裡真實的快照）：
  1. get_page_tool 讀教務處「休學-保留學籍-退學-提早復學」頁面（標頭、ledger 標記行、[偵測到表單編號]、全文）
  2. resource_node 注入一則 HumanMessage：「[表單全文，…]」加上頁面偵測到的**全部**表單（QP-T01-02-05、QP-T01-03-02、
     QP-T01-03-04，排序後；每張是 get_form 取得表單 <標題> + ledger 標記行 + 全文）
  沒有重現 contact_node 的聯絡人清單與 [偵測到辦公室]（那需要 LLM 判斷辦公室），這一題用不到。
model／system_version／label 明確標示假設；不放 runs/，所以 list_runs.py 與之後的彙整都讀不到。

用法（專案根目錄）：
  python evaluation/leave_form_download/tests/pipeline_setup/make_runs.py
已存在的案例資料夾不覆蓋（避免新舊檔案混在一起），要重做請先自己刪掉那個資料夾。
"""
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUESTION = HERE.parents[1]                  # evaluation/leave_form_download
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evaluation"))
import run_system  # noqa: E402  (設好 LIVE_BROWSER=off 等環境變數)
from rag.live.ledger import DISCLOSURE_HEADER, make_marker  # noqa: E402

PAGE_URL = "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學"
PAGE_TITLE = "休學-保留學籍-退學-提早復學"
FORM_IDS = ["QP-T01-02-05", "QP-T01-03-02", "QP-T01-03-04"]        # extract_form_ids 的結果，排序後
CASES = ["complete", "aca_link_only", "wrong_form", "verbose"]
LABEL = "假設答案，流程測試，不計分"
MODEL = "hypothetical（Claude Code 撰寫，不是系統輸出）"
BODY_MARK = "# 以下為該筆記錄的 text 欄位全文（逐字複本）"
RESOURCE_PREFIX = "[表單全文，系統偵測到表單編號後自動抓取，請直接引用其中的流程/站點/費用等細節]\n\n"


def link_url_for(form_id: str) -> str:
    return f"https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail={form_id}"


def page_text() -> str:
    raw = (QUESTION / "sources" / "snapshot" / "aca_leave_page.txt").read_text(encoding="utf-8")
    return raw.split(BODY_MARK, 1)[1].strip()


def form_records() -> dict[str, dict]:
    """output/aca/supplementary_map.json（標題）與 extracted_supplementary.jsonl（全文），都是本地快照。"""
    titles = {e["form_id"]: e["form_title"] for e in json.loads((ROOT / "output/aca/supplementary_map.json").read_text(encoding="utf-8"))
              if e.get("form_id") in FORM_IDS}
    texts = {}
    for line in (ROOT / "output/aca/extracted_supplementary.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        for fid in FORM_IDS:
            if d["url"] == link_url_for(fid):
                texts[fid] = d["text"]
    missing = [f for f in FORM_IDS if f not in titles or f not in texts]
    if missing:
        raise SystemExit(f"找不到表單的快照：{missing}")
    return {f: {"title": titles[f], "text": texts[f]} for f in FORM_IDS}


def build_context() -> list[dict]:
    text = page_text()
    marker = make_marker(PAGE_URL, status="snapshot", checked="", snap="2026-08")
    page = (f"get_page 取得 {len(text)} 字，標題: {PAGE_TITLE}，subdomain: aca\n{marker}\n"
            f"[偵測到表單編號: {', '.join(FORM_IDS)}]\n\n全文：\n{text}")
    forms = form_records()
    blocks = []
    for fid in FORM_IDS:
        m = make_marker(link_url_for(fid), status="snapshot", checked="", snap="2026-08", kind="form")
        blocks.append(f"get_form 取得表單 {forms[fid]['title']}\n{m}\n\n全文：\n{forms[fid]['text']}")
    return [
        {"message_index": 1, "role": "ToolMessage", "tool": "get_page_tool", "text": page},
        {"message_index": 2, "role": "HumanMessage", "tool": None, "text": RESOURCE_PREFIX + "\n\n".join(blocks)},
    ]


def answer_raw(body: str) -> str:
    urls = [PAGE_URL, link_url_for("QP-T01-03-02")]
    src = "來源：" + urls[0] + "\n" + "\n".join(f"- {u}" for u in urls[1:])
    footer = f"{DISCLOSURE_HEADER}\n- 使用資料庫（快照）：{len(urls)} 頁\n" + "\n".join(f"  - {u}" for u in urls)
    return f"{body.strip()}\n\n{src}\n\n---\n{footer}"


def main() -> int:
    gold = json.loads((QUESTION / "gold.json").read_text(encoding="utf-8"))
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    for name in CASES:
        if (HERE / name).exists():
            print(f"已存在，不覆蓋：{(HERE / name).relative_to(ROOT)}", file=sys.stderr)
            return 1
    made = []
    for name in CASES:
        raw = answer_raw((HERE / "answers" / f"{name}.txt").read_text(encoding="utf-8"))
        body, stripped = run_system.split_answer(raw)
        pred = {
            "query_id": gold["query_id"], "query": gold["query"], "run_id": name, "label": LABEL,
            "started_at": now, "finished_at": now, "system_version": "hypothetical", "model": MODEL,
            "live": False, "live_fetch_env": None,
            "answer_raw": raw, "answer_body": body, "stripped": stripped,
            "context": build_context(), "checks": {"contact_pages": [], "contact_consistency": []},
            "trace": {"query_type": "resource", "turn": 1, "self_eval_note": None, "subdomain_hint": "aca", "tool_calls": []},
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
