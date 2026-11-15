#!/usr/bin/env python3
"""
scripts/update_moved_staff_pages_in_index.py

一次性處理（2026-11-15）：總務處 8 個單位的人員頁搬到 nccuga.nccu.edu.tw（F19，rag/live/moved_pages.json），
但聯絡人索引 output/office_contacts_index.jsonl 還是舊網址、8/25 的舊站文字。這支程式把那 8 行「原地」換成新頁：

  改：url（新網址）、text（新頁面的文字）、fetched_at（頁面實際取得的日期時間）
  不改：category、name、subdomain（domain_router 靠 subdomain 決定要搜哪個語料資料夾，例如出納組 → cashier）；
        行的位置（索引的順序有用處）；其他 426 行逐字不動

同時把 docs/contact.csv（索引的來源清單）那 8 列的網址改成新網址，格式不變，之後重新產生索引才不會改回舊的。

為什麼是「取代」不是「新增」：系統用名稱查索引，同名的記錄全部都讀；新增一筆會讓同一個單位讀兩頁、聯絡人重複。
為什麼不重跑 rag/fetch_office_contacts.py：它沒有取代模式（--resume 是接在後面），不加 --resume 則重抓全部 434 頁；
而且它的 CSV_PATH 指向已經不存在的 docs/FindURLs/contact.csv。

新頁面的文字不重新抓：用 evaluation/registry/sources/live/ga_*.rendered.html（2026-11-13 用系統的 Playwright 後端渲染存下來的，
每份旁邊的 .render.json 記了網址與取得時間），經 rag.preprocess.extract_html_bytes（爬取當時用的同一個抽取函式）處理，
所以格式與系統現場讀取的一致。這支程式不連網。

用法（專案根目錄）：
  python scripts/update_moved_staff_pages_in_index.py            # 預演：只印每一筆會怎麼改，不寫任何檔案
  python scripts/update_moved_staff_pages_in_index.py --apply    # 寫入索引與 contact.csv

可重複執行：已經是新網址的行會跳過。舊網址找不到或有多筆、頁面檔缺、抽取結果是空的，一律停下，什麼都不寫。
"""
import argparse
import json
import os
import sys

# 這支程式不連網；import 系統程式碼前先關掉 Chromium 與 Langfuse（Langfuse 沒開時 span 匯出會一直重試洗版）
os.environ["LIVE_BROWSER"] = "off"
os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")
import tempfile
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "output" / "office_contacts_index.jsonl"
MOVED = ROOT / "rag" / "live" / "moved_pages.json"
CSV = ROOT / "docs" / "contact.csv"
PAGES_DIR = ROOT / "evaluation" / "registry" / "sources" / "live"
MIN_PAGE_CHARS = 100                    # 真的人員頁最短的（規劃組）也有 700 多字

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_moved(path: Path = MOVED) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["pages"]


def load_pages(pages_dir: Path = PAGES_DIR) -> dict[str, dict]:
    """{新網址（解碼後）: {"html": 檔案, "fetched_at": 'YYYY-MM-DDTHH:MM:SS', "url": 原樣網址}}，只收 ok 的渲染結果。"""
    pages: dict[str, dict] = {}
    for meta in sorted(Path(pages_dir).glob("*.render.json")):
        d = json.loads(meta.read_text(encoding="utf-8"))
        html = meta.with_name(meta.name.replace(".render.json", ".rendered.html"))
        if not d.get("ok") or not html.exists():
            continue
        pages[unquote(d["url"])] = {"html": html, "fetched_at": (d.get("fetched_at") or "")[:19], "url": d["url"]}
    return pages


def _contacts(text: str) -> set[tuple[str, str]]:
    from rag.skills.office_lookup_skill import parse_office_contacts
    return {(c["name"], c["ext"]) for c in parse_office_contacts(text)}


def make_plan(index_lines: list[str], moved: list[dict], pages: dict[str, dict]) -> list[dict]:
    """每個搬家的頁面一筆計畫：action 是 replace｜already｜error。不寫任何檔案。"""
    from rag.preprocess import extract_html_bytes
    recs = [json.loads(line) for line in index_lines]
    plans = []
    for m in moved:
        old, new = m["old"], m["new"]
        p = {"unit": m["unit"], "old": old, "new": new, "action": "error", "error": None, "line": None}
        at_old = [i for i, r in enumerate(recs) if r.get("url") == old]
        at_new = [i for i, r in enumerate(recs) if r.get("url") == new]
        if at_old and at_new:
            p["error"] = "索引裡舊網址與新網址同時存在（會重複）"
        elif at_new and len(at_new) == 1:
            p.update(action="already", line=at_new[0] + 1)
        elif len(at_old) != 1:
            p["error"] = f"索引裡舊網址應該剛好一筆，實際 {len(at_old)} 筆"
        else:
            page = pages.get(unquote(new))
            if page is None:
                p["error"] = "找不到這個新網址的渲染頁面（.render.json 的 url 對不上，或沒有 ok）"
            else:
                text = extract_html_bytes(page["html"].read_bytes(), new)
                if len(text.strip()) < MIN_PAGE_CHARS:       # 空頁面抽出來不是空字串，而是網址的最後一段（例如 'y'），所以用長度擋
                    p["error"] = f"新頁面抽出來幾乎是空的（{len(text.strip())} 字，少於 {MIN_PAGE_CHARS}）"
                else:
                    old_rec = recs[at_old[0]]
                    new_rec = dict(old_rec)                       # 欄位與順序不變，只換下面三個
                    new_rec["url"], new_rec["text"], new_rec["fetched_at"] = new, text, page["fetched_at"]
                    old_c, new_c = _contacts(old_rec["text"]), _contacts(text)
                    p.update(action="replace", line=at_old[0] + 1, new_rec=new_rec, old_chars=len(old_rec["text"]), new_chars=len(text),
                             old_fetched=old_rec.get("fetched_at"), new_fetched=page["fetched_at"],
                             only_old=sorted(old_c - new_c), only_new=sorted(new_c - old_c), n_old=len(old_c), n_new=len(new_c))
        plans.append(p)
    return plans


def apply_to_index(index_lines: list[str], plans: list[dict]) -> list[str]:
    """只換 replace 那幾行；其餘逐字不動。"""
    out = list(index_lines)
    for p in plans:
        if p["action"] == "replace":
            out[p["line"] - 1] = json.dumps(p["new_rec"], ensure_ascii=False)
    return out


def update_csv(csv_text: str, plans: list[dict]) -> tuple[str, list[str]]:
    """contact.csv：把每個搬家頁面的舊網址換成新網址，只換在行尾的那一格（格式不變）。回傳 (新文字, 有改的單位)。"""
    lines = csv_text.split("\n")
    changed = []
    for p in plans:
        if p["action"] == "error":
            continue
        hits = [i for i, ln in enumerate(lines) if ln.endswith("," + p["old"])]
        if len(hits) == 1:
            lines[hits[0]] = lines[hits[0]][: -len(p["old"])] + p["new"]
            changed.append(p["unit"])
        elif len(hits) > 1:
            raise ValueError(f"contact.csv 裡 {p['unit']} 的舊網址出現 {len(hits)} 列")
    return "\n".join(lines), changed


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=Path(path).parent, prefix=Path(path).name + ".")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def report(plans: list[dict], say=print) -> None:
    for p in plans:
        head = f"{p['unit']}：{p['action']}"
        if p["action"] == "error":
            say(f"{head}：{p['error']}")
        elif p["action"] == "already":
            say(f"{head}（索引第 {p['line']} 行已經是新網址）")
        else:
            say(f"{head}（索引第 {p['line']} 行）{p['old_chars']} 字 → {p['new_chars']} 字；取得時間 {p['old_fetched']} → {p['new_fetched']}；"
                f"解析出的聯絡人 {p['n_old']} → {p['n_new']} 人")
            for label, key in (("  只在舊頁", "only_old"), ("  只在新頁", "only_new")):
                if p[key]:
                    say(f"{label}：" + "、".join(f"{n}({e})" for n, e in p[key]))
            if p["n_new"] == 0:
                say("  [警告] 新頁面文字解析不出任何聯絡人")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="寫入索引與 contact.csv；沒有這個旗標只是預演")
    ap.add_argument("--index", type=Path, default=INDEX)
    ap.add_argument("--csv", type=Path, default=CSV)
    ap.add_argument("--moved", type=Path, default=MOVED)
    ap.add_argument("--pages-dir", type=Path, default=PAGES_DIR)
    a = ap.parse_args(argv)

    raw = a.index.read_text(encoding="utf-8")
    lines = raw.split("\n")
    trailing = lines[-1] == ""
    if trailing:
        lines = lines[:-1]
    plans = make_plan(lines, load_moved(a.moved), load_pages(a.pages_dir))
    report(plans)
    if any(p["action"] == "error" for p in plans):
        print("\n有錯誤，什麼都沒寫。")
        return 2
    n = sum(p["action"] == "replace" for p in plans)
    if not a.apply:
        print(f"\n預演結束：會改索引 {n} 行；沒有寫任何檔案。確認後加 --apply。")
        return 0
    new_lines = apply_to_index(lines, plans)
    new_csv, changed = update_csv(a.csv.read_text(encoding="utf-8"), plans) if a.csv.exists() else (None, [])
    _atomic_write(a.index, "\n".join(new_lines) + ("\n" if trailing else ""))
    if new_csv is not None:
        _atomic_write(a.csv, new_csv)
    print(f"\n已寫入：索引 {n} 行；contact.csv {len(changed)} 列。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
