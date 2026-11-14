"""
evaluation/dashboard/build_preview.py

index.html（本機完整檔，開啟後用「Choose File」載入 .jsonl）→ sample/preview.html：把 sample/preview_hypothetical.jsonl 內嵌進去，
並且去掉 <!doctype>、<html>、<head>、<body> 外層標籤（發布成 artifact 時由平台加上外層）。同一份原始碼，預覽只多內嵌資料。

用法（專案根目錄；先跑 export_scores.py 產生 .jsonl）：
  python evaluation/dashboard/build_preview.py
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "index.html"
DATA = HERE / "sample" / "preview_hypothetical.jsonl"
OUT = HERE / "sample" / "preview.html"
EMPTY = '<script id="initial-data" type="text/plain"></script>'


def build(src: str, data: str) -> str:
    if EMPTY not in src:
        raise ValueError("index.html 裡找不到空的 initial-data 區塊")
    head = re.search(r"<head>(.*?)</head>", src, re.S).group(1)
    body = re.search(r"<body>(.*?)</body>", src, re.S).group(1)
    # 平台自己加 charset 與 viewport，這兩個 meta 不重複寫
    head = re.sub(r'\s*<meta charset="utf-8">', "", head)
    head = re.sub(r'\s*<meta name="viewport"[^>]*>', "", head)
    safe = data.replace("</", "<\\/")                         # 資料裡不能出現 </script>
    body = body.replace(EMPTY, f'<script id="initial-data" type="text/plain">{safe}</script>')
    return head.strip() + "\n" + body.strip() + "\n"


def main() -> int:
    if not DATA.exists():
        print(f"找不到 {DATA}，請先跑 python evaluation/dashboard/export_scores.py")
        return 1
    out = build(SRC.read_text(encoding="utf-8"), DATA.read_text(encoding="utf-8"))
    OUT.write_text(out, encoding="utf-8")
    print(f"→ {OUT}（{len(out):,} 字元，{len(DATA.read_text(encoding='utf-8').splitlines())} 題）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
