"""
evaluation/registry/fetch_live_page.py

用專案自己的動態抓取（rag/live/browser.py 的 PlaywrightBackend：無頭 Chromium，開網址、等 load、再等 settle 讓 JavaScript 補內容、取 DOM）
把一個或幾個 nccu.edu.tw 的頁面抓下來，存成評測用的現場來源（單位登記表、gold 的來源）。人員頁、表單頁是 JavaScript 動態載入的，
靜態 curl 只拿得到選單，所以要用這個。

**對 nccu.edu.tw 的請求要使用者先批准**（CLAUDE.md）。這支腳本預設只列出要請求的網址（dry-run），加 --run 才真的送；網址要逐個寫在命令列上，
沒有預設清單，也不會自己跟著連結走。

  python evaluation/registry/fetch_live_page.py https://oic.nccu.edu.tw/Category/596 --name oic_category_596            # dry-run
  python evaluation/registry/fetch_live_page.py https://oic.nccu.edu.tw/Category/596 --name oic_category_596 --run      # 真的送

輸出（evaluation/registry/sources/live/）：
  <name>.rendered.html   渲染後的 DOM（UTF-8）
  <name>.render.json     請求記錄：網址、最後網址、狀態碼、耗時、頁面載入時發出的請求數（含 *.nccu.edu.tw 的）、時間、settle 毫秒
不使用 User-Agent 設定（Chromium 預設，不含 email）；每次渲染用全新的 context，cookie 不外洩。只允許 http(s) 的 *.nccu.edu.tw。
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "sources" / "live"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="+", help="要請求的網址（逐個寫，沒有預設清單）")
    ap.add_argument("--name", action="append", required=True, help="每個網址一個檔名（不含副檔名），順序與網址相同")
    ap.add_argument("--run", action="store_true", help="真的送請求；沒加就只列出來（dry-run）")
    args = ap.parse_args()
    if len(args.urls) != len(args.name):
        ap.error("--name 的個數要與網址相同")
    from rag.live import config
    from rag.live.allowlist import is_allowed

    bad = [u for u in args.urls if not is_allowed(u)]
    if bad:
        print(f"拒絕：不是 http(s) 的 *.nccu.edu.tw 網址：{bad}", file=sys.stderr)
        return 2
    print(f"{'將請求' if args.run else '[dry-run] 會請求'} {len(args.urls)} 個網址（Chromium 預設 User-Agent，settle {config.RENDER_SETTLE_MS} 毫秒）：")
    for u, n in zip(args.urls, args.name):
        print(f"  {u}  →  {OUT.relative_to(ROOT)}/{n}.rendered.html")
    if not args.run:
        print("沒有送出任何請求（加 --run 才會送）。")
        return 0

    from rag.live.browser import PlaywrightBackend

    OUT.mkdir(parents=True, exist_ok=True)
    backend = PlaywrightBackend()
    backend.start()
    code = 0
    try:
        for u, n in zip(args.urls, args.name):
            fetched = dt.datetime.now().astimezone().isoformat(timespec="seconds")
            r = backend.render(u)
            meta = {"url": u, "ok": r.ok, "status": r.status, "error": r.error, "detail": r.detail,
                    "elapsed_seconds": round(r.elapsed, 2), "requests": r.requests, "requests_nccu": r.requests_nccu,
                    "fetched_at": fetched, "tool": "rag.live.browser.PlaywrightBackend", "settle_ms": config.RENDER_SETTLE_MS,
                    "user_agent": "Chromium default (not set; no email)"}
            if r.ok:
                (OUT / f"{n}.rendered.html").write_bytes(r.html.removeprefix(b"\xef\xbb\xbf"))
            (OUT / f"{n}.render.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  {u} → ok={r.ok} status={r.status} {len(r.html)} 位元組，頁面共發出 {r.requests} 個請求（其中 *.nccu.edu.tw {r.requests_nccu} 個），{r.elapsed:.1f} 秒" + (f"  錯誤：{r.error} {r.detail}" if not r.ok else ""))
            code |= 0 if r.ok else 1
    finally:
        backend.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
