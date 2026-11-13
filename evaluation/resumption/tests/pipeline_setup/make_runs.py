"""
evaluation/resumption/tests/pipeline_setup/make_runs.py

流程測試用：把 answers/*.txt 的「假設答案」組成 prediction.json，讓整條評測管線（階段 2、階段 3、隔離回推、Keypoint 判斷）
假裝跑一次。**這不是系統的真實答案，分數不能當評測結果**（plan/phase_k_evaluation_design.md 的 13.6）。

證據照這一題（程序類、跨處室）真實的形狀組：
  1. get_page_tool 讀教務處「休學-保留學籍-退學-提早復學」頁面（標頭、ledger 標記行、[偵測到表單編號]、全文；快照原文）
  2. resource_node 注入表單全文（QP-T01-02-05、QP-T01-03-02、QP-T01-03-04；快照原文）
  3. contact_node 注入「辦公室聯絡資訊」：表單上的站點偵測到註冊組、生僑組、國際合作事務處。**這一則是假設的**：
     用 evaluation/registry/registry.json 照 contact_node 的版面排出來（名字取快照寫法，沒有名字的只寫職稱），
     不是真實 run 的輸出；真實的 contact_node 對國合處讀的是舊索引，沒有姓名（議題 F15）。
model／system_version／label 明確標示假設；不放 runs/，所以 list_runs.py 與之後的彙整都讀不到。

用法（專案根目錄）：
  python evaluation/resumption/tests/pipeline_setup/make_runs.py
已存在的案例資料夾不覆蓋、直接略過，只補缺的；要重做請先自己刪掉那個資料夾。
"""
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUESTION = HERE.parents[1]                  # evaluation/resumption
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evaluation"))
sys.path.insert(0, str(ROOT / "evaluation" / "registry"))
import run_system  # noqa: E402  (設好 LIVE_BROWSER=off 等環境變數)
import registry_lib  # noqa: E402
from rag.live.ledger import DISCLOSURE_HEADER, make_marker  # noqa: E402

PAGE_URL = "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學"
PAGE_TITLE = "休學-保留學籍-退學-提早復學"
FORM_IDS = ["QP-T01-02-05", "QP-T01-03-02", "QP-T01-03-04"]        # extract_form_ids 的結果，排序後
CASES = ["complete", "missing_links", "wrong_pairs", "live_forms", "minimal"]
OFFICE_PAGES = {   # 登記表單位 → (要顯示的名稱, 樓層字串, 來源網址)
    "registrar": ("註冊組", "行政大樓 4 樓", "https://aca.nccu.edu.tw/zh/人員職掌-註冊"),
    "soa": ("生僑組", "行政大樓 3 樓", "https://osa.nccu.edu.tw/tw/生活事務暨僑生輔導組/關於我們/成員介紹"),
    "oic": ("國際合作事務處", "行政大樓 8 樓", "https://oic.nccu.edu.tw/Category/596"),
}
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


def contact_block() -> str:
    reg = registry_lib.load()
    lines = ["[辦公室聯絡資訊，以下是內容中提及的全部 3 個辦公室（註冊組、生僑組、國際合作事務處），未經相關性篩選——這是完整清單，"
             "不代表每一個都跟這題直接相關。是否每個都要寫進最終答案由你根據問題判斷，不要假設清單已經先篩過。]", "", "【各辦公室聯絡資訊】"]
    for okey, (name, floor, url) in OFFICE_PAGES.items():
        o = registry_lib.office(reg, okey)
        lines.append(f"  {name}　{floor}")
        for ln in o["lines"]:
            lines.append(f"    ☎ {name}：{ln['kind']} {ln['value']}")
        for e in o["staff"]:
            snap = [n["value"] for n in e["names"] if any(s["source"] == "snapshot" for s in n["sources"])]
            who = (snap or [n["value"] for n in e["names"]] or [""])[0]
            title = e["titles"][0]["value"] if e["titles"] else ""
            who_part = f"{who}（{title}）" if who else f"（{title}）"
            lines.append(f"    • {who_part}分機 {e['ext'] or '無'}")
        lines.append(f"    來源：{url}")
    return "\n".join(lines)


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
    contact = contact_block()
    return [
        {"message_index": 1, "role": "ToolMessage", "tool": "get_page_tool", "text": page},
        {"message_index": 2, "role": "HumanMessage", "tool": None, "text": RESOURCE_PREFIX + "\n\n".join(blocks)},
        {"message_index": 3, "role": "HumanMessage", "tool": None, "text": contact},
    ]


def answer_raw(body: str) -> str:
    urls = [PAGE_URL, link_url_for("QP-T01-03-04")] + [u for _, _, u in OFFICE_PAGES.values()]
    src = "來源：" + urls[0] + "\n" + "\n".join(f"- {u}" for u in urls[1:])
    footer = f"{DISCLOSURE_HEADER}\n- 使用資料庫（快照）：{len(urls)} 頁\n" + "\n".join(f"  - {u}" for u in urls)
    return f"{body.strip()}\n\n{src}\n\n---\n{footer}"


def main() -> int:
    gold = json.loads((QUESTION / "gold.json").read_text(encoding="utf-8"))
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    made = []
    for name in CASES:
        if (HERE / name).exists():
            print(f"已存在，略過：{(HERE / name).relative_to(ROOT)}")
            continue
        raw = answer_raw((HERE / "answers" / f"{name}.txt").read_text(encoding="utf-8"))
        body, stripped = run_system.split_answer(raw)
        pred = {
            "query_id": gold["query_id"], "query": gold["query"], "run_id": name, "label": LABEL,
            "started_at": now, "finished_at": now, "system_version": "hypothetical", "model": MODEL,
            "live": False, "live_fetch_env": None,
            "answer_raw": raw, "answer_body": body, "stripped": stripped,
            "context": build_context(), "checks": {"contact_pages": [], "contact_consistency": []},
            "trace": {"query_type": "procedure", "turn": 1, "self_eval_note": None, "subdomain_hint": "aca", "tool_calls": []},
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
