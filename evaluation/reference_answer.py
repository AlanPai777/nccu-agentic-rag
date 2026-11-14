"""
evaluation/reference_answer.py

gold.json 的 reference_answer（畫面用的完整參考答案，不參與評分）的標記解析。共用於 gold_check.py（建置檢查）與 dashboard/export_scores.py（匯出）。

文字像 Prediction 一樣是一份真實的回答（可以有 **粗體**、項目符號、編號），只在需要的地方加標記：

  {{固定|(02) 2939-3091}}                  不可替換：hard 事實，必須完全一致（只標直接回答題目的數字、表單編號與連結、有順序的流程）
  {{可替換:K2|劉桂芬（組長）分機 62120}}     可替換：登記表人員或分機（K2 是這個 keypoint 的編號，清單由它帶出）；姓名須對上分機
  {{選答}}                                 這一句是選答的 keypoint，畫面上顯示淡灰的「（選答）」

其餘文字不標（語意相符即可）。有條件才適用的內容直接在句尾用括號寫適用條件，例如「（住宿生適用）」。
"""
import re

_TOKEN = re.compile(r"\{\{(固定|可替換:[^|{}]+|選答)(?:\|([^{}]*))?\}\}")


def parse(text: str) -> list[dict]:
    """回傳片段清單：{"t": "text"|"fixed"|"rep"|"opt", "v": 文字, "kp": 編號（只有 rep）}。標記不合法就丟 ValueError。"""
    segs, pos = [], 0
    for m in _TOKEN.finditer(text):
        if m.start() > pos:
            segs.append({"t": "text", "v": text[pos:m.start()]})
        kind, val = m.group(1), m.group(2)
        if kind == "固定":
            if not val:
                raise ValueError("{{固定|…}} 沒有內容")
            segs.append({"t": "fixed", "v": val})
        elif kind == "選答":
            segs.append({"t": "opt", "v": "（選答）"})
        else:
            if not val:
                raise ValueError(f"{{{{{kind}|…}}}} 沒有內容")
            segs.append({"t": "rep", "v": val, "kp": kind.split(":", 1)[1].strip()})
        pos = m.end()
    rest = text[pos:]
    if "{{" in rest or "}}" in rest or any("{{" in s["v"] or "}}" in s["v"] for s in segs):
        raise ValueError("標記沒有成對或格式不對")
    if rest:
        segs.append({"t": "text", "v": rest})
    return segs


def attach(gold: dict, here) -> None:
    """題目資料夾有 reference_answer.txt 就放進 gold（畫面用的完整參考答案，不參與評分；檔案用 UTF-8，結尾換行會去掉）。"""
    from pathlib import Path
    f = Path(here) / "reference_answer.txt"
    if f.exists():
        gold["reference_answer"] = f.read_text(encoding="utf-8").rstrip("\n")
