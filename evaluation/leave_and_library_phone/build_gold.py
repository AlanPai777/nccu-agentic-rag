"""
evaluation/leave_and_library_phone/build_gold.py

建「如何辦理休學，圖書館的電話是多少」的 gold（複合題：第 5 題的休學流程 + 圖書館電話）。

A 部分（K1–K60）：整份從 evaluation/leave_of_absence/gold.json 匯入（那一份是唯一的定義，由它的 build_gold.py 建；這裡只複製，不改），
來源資料夾（sources/）也從那一題複製過來，這樣每題仍然自己帶著自己的證據（議題 F17：決定不去重）。
B 部分（K61 起）：圖書館電話。電話全部引用登記表（`"registry": {"need": "line", ...}`；引句在登記表，各題共用）：
  - 登記表的圖書館電話來自：圖書館「各組聯絡資訊」頁（快照 2026-08-25 與現場 2026-11-13）、教務處「圖書資源」頁、統計系「常用行政電話」
  - 典藏閱覽組那一格顯示 (02)2938-7878，但連結的 tel: 目標是學校總機；顯示文字有統計系頁面的獨立佐證，連結目標視為連結本身的筆誤

用法（專案根目錄，不上網）：
  python evaluation/leave_of_absence/build_gold.py && python evaluation/leave_and_library_phone/build_gold.py
輸出：evaluation/leave_and_library_phone/gold.json、sources/（複本）
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "evaluation"))
import gold_check  # noqa: E402

Q5 = ROOT / "evaluation" / "leave_of_absence"
REG_LIVE = ROOT / "evaluation" / "registry" / "sources" / "live"

LIB_LINES = [  # (id, 文字, 登記表的 line key, 必要?)
    ("K61", "總圖（中正館流通櫃臺、典藏閱覽組）借還書的校內分機是 63222", "main_ext", True),
    ("K62", "典藏閱覽組的直撥電話是 (02)2938-7878", "direct", False),
    ("K63", "政大總機是 (02)29393091", "switchboard", False),
    ("K64", "綜圖的校內分機是 50107", "zonghe_ext", False),
    ("K65", "商圖的校內分機是 84006", "shang_ext", False),
    ("K66", "傳圖的校內分機是 67152", "chuan_ext", False),
    ("K67", "達賢圖的電話是 (02)82377017", "daxian", False),
]


def main() -> int:
    if not (Q5 / "gold.json").exists():
        raise SystemExit("先建第 5 題的 gold：python evaluation/leave_of_absence/build_gold.py")
    g5 = json.loads((Q5 / "gold.json").read_text(encoding="utf-8"))
    shutil.copytree(Q5 / "sources", HERE / "sources", dirs_exist_ok=True)
    for name in ("lib_contact_units.rendered.html", "lib_contact_units.render.json"):
        shutil.copy(REG_LIVE / name, HERE / "sources" / "live" / name)
    a = [{**k, "part": "A"} for k in g5["keypoints"]]
    b = [{"id": kid, "text": text, "required": req, "kind": "hard", "value_check": "registry_line", "part": "B",
          "registry": {"office": "library", "need": "line", "line": key}} for kid, text, key, req in LIB_LINES]
    gold = {
        "query_id": "leave_and_library_phone",
        "query": "如何辦理休學，圖書館的電話是多少",
        "query_variants": [],
        "query_type": "compound",
        "data_as_of": {**g5["data_as_of"], "library_phone": "圖書館各組聯絡資訊頁：快照 2026-08-25、現場 2026-11-13（動態）"},
        "content": g5["content"] + (
            " 圖書館的電話：總圖（中正館流通櫃臺、典藏閱覽組）借還書是 (02)2939-3091 轉分機 63222，直撥 (02)2938-7878；"
            "綜圖分機 50107、商圖 84006、傳圖 67152；達賢圖 (02)82377017。"),
        "keypoints": a + b,
        "source_conflicts": g5.get("source_conflicts", "") + (
            " 圖書館電話：典藏閱覽組那一格顯示 (02)2938-7878，連結的 tel: 目標卻是學校總機 +886229393091（其他各組的連結目標與顯示相同）；"
            "顯示文字有統計系「常用行政電話一覽表」的獨立佐證，連結目標視為連結本身的筆誤（2026-11-13 現場確認）。"
            "統計系頁面把達賢圖書館寫成 (02)8237-7000（總機），聯絡頁寫達賢圖 (02)82377017（數位創新組直撥），兩個不是同一個號碼，B 部分只收聯絡頁寫的。"),
        "notes": g5["notes"] + [
            "複合題：A 部分（K1–K60）整份匯入第 5 題，B 部分（K61–K67）是圖書館電話；每個 keypoint 有 part 欄位（A／B），"
            "報告用 part_scores.py 另外列兩部分各自的 Completeness。",
            "B 部分的電話全部引用登記表圖書館的 lines（每條附逐字引句與來源）；K61（總圖借還書分機 63222）列為必要，其餘選擇性。"
            "「必要」目前不影響評分（議題 F8、F9）。",
            "圖書館的「找誰」（人名加分機）不列：申請書只寫「總圖或分館借還書櫃檯」，沒有指定承辦人（第 5 題使用者決定）；這題問的是電話，不是人。",
            "答案寫 (02)2939-3091 轉 63222 時，K61（分機）與 K63（總機）都算命中；電話只比數字，區碼 0 或 02 有沒有寫、中間的 - 或空白都不影響。",
        ],
    }
    out = HERE / "gold.json"
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    problems = gold_check.validate_gold(out)
    if problems:
        out.unlink()
        raise SystemExit("gold 驗證失敗，沒有寫檔：\n  - " + "\n  - ".join(problems))
    print(f"已寫入 {out.relative_to(ROOT)}（{len(a)} 個匯入第 5 題 + {len(b)} 個圖書館電話，共 {len(a) + len(b)}；{sum(1 for k in a + b if k.get('registry'))} 個引用登記表）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
