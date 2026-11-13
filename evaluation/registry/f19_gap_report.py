"""
evaluation/registry/f19_gap_report.py

F19（總務處 8 個單位的人員頁搬到 nccuga.nccu.edu.tw）的差距報告，只讀、離線、不呼叫 LLM、不上網。

做兩件事：
  1. 登記表狀態（both／changed／live-only／snapshot-only／title-only）給出每個單位新舊頁面的差異。
  2. 用系統**原本的前處理**（rag/preprocess.py 的 extract_html_bytes，live 路徑與建語料共用）讀這 8 個新頁面，再用原本的
     人員解析（office_lookup_skill._parse_labeled，只跑規則那一層，不呼叫 LLM）看能讀出幾個人，並與登記表比對正確的有幾個；
     同時算新頁面文字與舊索引文字的相似度（系統用它決定要不要升級成瀏覽器渲染，門檻 LIVE_STATIC_SIMILARITY_MIN=0.5）。

用法（專案根目錄）：
  LIVE_BROWSER=off python evaluation/registry/f19_gap_report.py --label before   # 或 after（修了前處理之後）
輸出：evaluation/registry/f19_gap_<label>.json；兩份都存在時另寫 evaluation/registry/f19_gap_report.md
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

UNITS = [  # (登記表鍵, 現場檔名)
    ("ga_dean", "ga_dean"), ("docu", "ga_docu"), ("aff", "ga_aff"), ("wealth", "ga_wealth"),
    ("mend", "ga_mend"), ("cashier", "ga_cashier"), ("safety", "ga_safety"), ("planning", "ga_planning"),
]


def analyse() -> dict:
    from rag.live.compare import compare
    from rag.preprocess import extract_html_bytes
    from rag.skills.office_lookup_skill import _parse_labeled

    reg = json.loads((HERE / "registry.json").read_text(encoding="utf-8"))["offices"]
    out = {}
    for key, live_name in UNITS:
        o = reg[key]
        raw = (HERE / "sources" / "live" / f"{live_name}.rendered.html").read_bytes()
        text = extract_html_bytes(b"\xef\xbb\xbf" + raw, "https://nccuga.nccu.edu.tw/zh/")
        contacts, needs_llm = _parse_labeled(text)
        live_exts = {e["ext"] for e in o["staff"] if e["ext"] and any(s["source"] == "live" for t in e["titles"] for s in t["sources"])}
        by_ext = {e["ext"]: e for e in o["staff"]}
        right = 0
        for c in contacts:
            e = by_ext.get(c.get("ext"))
            names = [n["value"] for n in e["names"]] if e else []
            right += bool(names and c.get("name") and any(n[0] == c["name"][0] for n in names))
        # 舊索引文字（有的單位沒有）
        snap = ""
        for s in o["staff"]:
            pass
        snap_file = None
        for w in o.get("where_to_find", []):
            if w.get("role", "").startswith("快照") and w.get("line"):
                snap_file = w["line"]
        sim = None
        if snap_file:
            rec = json.loads((ROOT / "output" / "office_contacts_index.jsonl").read_text(encoding="utf-8").splitlines()[snap_file - 1])
            sim = round(compare(rec["text"], text).similarity, 3)
        statuses = {}
        for e in o["staff"]:
            statuses[e["status"]] = statuses.get(e["status"], 0) + 1
        out[key] = {
            "name": o["name"], "registry_people": len(o["staff"]), "registry_status": statuses,
            "live_text_chars": len(text), "text_has_names": bool(re.search(r"[一-鿿]{2,4}\s+(組長|組員|專員|技士|助教|秘書|編審|技正|工友|隊員)", text)),
            "parsed_contacts": len(contacts), "parsed_correct": right, "parse_falls_back_to_llm": bool(needs_llm),
            "similarity_to_old_snapshot": sim,
            "escalates_to_browser": (sim is not None and sim < 0.5),
        }
    return out


def write_md() -> None:
    before = json.loads((HERE / "f19_gap_before.json").read_text(encoding="utf-8"))
    after = json.loads((HERE / "f19_gap_after.json").read_text(encoding="utf-8"))
    lines = ["# F19 差距報告：總務處 8 個單位的人員頁（舊索引 2026-08-25 vs 新頁面 2026-11-13）", "",
             "只讀、離線、不呼叫 LLM（`f19_gap_report.py`）。「解析」是系統原本的規則解析（`_parse_labeled`），不是登記表的專用解析。", "",
             "| 單位 | 登記表人數 | 狀態（both／changed／live-only／snapshot-only／title-only） | 相似度（新頁 vs 舊索引） | 原前處理：文字有姓名 | 原前處理：解析出／正確 | 修正後：解析出／正確 |",
             "|---|---|---|---|---|---|---|"]
    for k, b in after.items():
        a0 = before[k]                                   # the original-preprocessing columns come from the run made before the fix
        a = dict(b)
        st = "／".join(str(a["registry_status"].get(x, 0)) for x in ("both", "changed", "live-only", "snapshot-only", "title-only"))
        sim = "—（索引沒有）" if a["similarity_to_old_snapshot"] is None else f"{a['similarity_to_old_snapshot']}" + ("（<0.5，會升級成瀏覽器渲染）" if a["escalates_to_browser"] else "")
        lines.append(f"| {a['name']} | {a['registry_people']} | {st} | {sim} | {'有' if a0['text_has_names'] else '**沒有**'} | {a0['parsed_contacts']}／{a0['parsed_correct']} | "
                     f"{b['parsed_contacts']}／{b['parsed_correct']}（{'需要 LLM 補救' if b['parse_falls_back_to_llm'] else '規則解析即可'}） |")
    (HERE / "f19_gap_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", choices=["before", "after"], required=True)
    args = ap.parse_args()
    res = analyse()
    (HERE / f"f19_gap_{args.label}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for k, a in res.items():
        print(f"{a['name']}: 人 {a['registry_people']}, 文字有姓名 {a['text_has_names']}, 解析 {a['parsed_contacts']}/{a['parsed_correct']} (LLM {a['parse_falls_back_to_llm']}), 相似度 {a['similarity_to_old_snapshot']}")
    if (HERE / "f19_gap_before.json").exists() and (HERE / "f19_gap_after.json").exists():
        write_md()
        print("已寫 f19_gap_report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
