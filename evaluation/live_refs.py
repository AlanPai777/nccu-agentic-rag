"""
evaluation/live_refs.py

gold 的事實以新網站（現場頁面）為準（2026-11-15，plan 13.19）。這支程式幫各題的 build_gold.py 補現場引用：

  對每個「有引用、但一條現場引用都沒有」的 keypoint，它的每一條快照引用（表單內容除外，現場要登入看不到），
  如果原文（空白正規化後）逐字在該題 sources/live/ 的某個現場來源裡，就加一條同一句話的 live 引用，出處是那個現場來源。

只新增，不改、不刪現有的引用；找不到逐字原文的不加（那代表現場頁面的說法不同或沒有，要人看）。
引用只是「這個事實的出處」，gold_check 仍然驗證它們逐字在來源裡；它們不再拿來和系統讀到的文字比對（in_context 由 Claude 判斷）。
"""
from pathlib import Path

import gold_check as gc


def _live_text(path: Path, is_html: bool) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    return gc.html_to_text(raw) if is_html else raw


def add_live_references(gold: dict, live_dir: Path, sources: list[tuple[str, str, str]]) -> list[str]:
    """sources: [(url, 檔名, as_of)]，檔名在 live_dir 底下；.html 轉成文字，其他（.pdf.txt、.txt）直接讀。
    回傳有加引用的 keypoint id。"""
    texts = []
    for url, fname, as_of in sources:
        f = Path(live_dir) / fname
        if f.exists():
            texts.append((url, as_of, gc.norm(_live_text(f, fname.endswith(".html")))))
    changed = []
    for k in gold["keypoints"]:
        refs = k.get("references") or []
        if not refs or any(r.get("source_kind") == "live" for r in refs):
            continue
        added = False
        for r in list(refs):
            if r.get("source_kind") != "snapshot" or "formservice" in (r.get("source_url") or ""):
                continue
            n = gc.norm(r["text"])
            for url, as_of, text in texts:
                if n and n in text:
                    refs.append({"text": r["text"], "source_url": url, "source_kind": "live", "as_of": as_of})
                    added = True
                    break
        if added:
            changed.append(k["id"])
    return changed
