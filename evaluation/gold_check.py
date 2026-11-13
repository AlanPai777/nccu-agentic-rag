"""
evaluation/gold_check.py

gold.json 的機械檢查（不判斷內容寫得好不好，那要人讀）。回傳問題清單，空清單代表通過。
單元測試（evaluation/tests/test_gold_files.py）與 build-eval-gold skill 的驗證腳本共用這一份。

  - 必要欄位齊全、keypoint 編號不重複、每個 keypoint 有 references
  - 每個 reference 的 text 都是該題 sources/ 底下某份來源原文的子字串（空白與全半形正規化後）
  - 有 value_check 的 keypoint 與 allowed_values 一致；條件式 keypoint 有 applies_if 與 value_check
  - 禁止值不在允許集合裡

用法（專案根目錄）：
  python evaluation/gold_check.py evaluation/cashier_contact/gold.json      # 結束碼 0 通過，1 有問題，2 檔案缺漏
"""
import html
import json
import re
import sys
import unicodedata
from pathlib import Path


def norm(s: str) -> str:
    return re.sub(r"[\s|]+", "", unicodedata.normalize("NFKC", s or ""))


_ANCHOR_RE = re.compile(r'(?is)<a\b[^>]*?\bhref\s*=\s*"([^"]*)"[^>]*>(.*?)</a>')


def html_to_text(raw: str) -> str:
    """現場 HTML → 文字。連結寫成 [文字](網址)（與快照裡的 markdown 連結同形），其餘標籤去掉；
    不這樣做的話，只出現在 href 屬性裡的網址（例如表單連結）就會從文字裡消失，引句驗證不到。"""
    raw = re.sub(r"(?s)<(script|style).*?</\1>", "", raw)
    raw = _ANCHOR_RE.sub(lambda m: "[" + re.sub(r"<[^>]+>", "", m.group(2)).strip() + "](" + m.group(1) + ")", raw)
    return html.unescape(re.sub(r"<[^>]+>", "\n", raw))


def source_text(question_dir: Path) -> str:
    """該題 sources/ 底下所有來源原文：snapshot 的 .txt、live 的 .html（連結寫成 [文字](網址)，其餘標籤去掉）、live 的 PDF 轉出的 .pdf.txt。"""
    parts = []
    for p in sorted((question_dir / "sources" / "snapshot").glob("*.txt")):
        parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    for p in sorted((question_dir / "sources" / "live").glob("*.pdf.txt")):
        parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    for p in sorted((question_dir / "sources" / "live").glob("*.html")):
        parts.append(html_to_text(p.read_text(encoding="utf-8", errors="ignore")))
    return norm("\n".join(parts))


def validate_gold(gold_path: Path) -> list[str]:
    gold_path = Path(gold_path)
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    src = source_text(gold_path.parent)
    problems: list[str] = []
    if not src:
        problems.append("sources/ 底下沒有來源文字")
    for key in ("query_id", "query", "content", "keypoints", "data_as_of"):
        if key not in gold:
            problems.append(f"缺少欄位 {key}")
    kps = gold.get("keypoints", [])
    ids = [k.get("id") for k in kps]
    if len(ids) != len(set(ids)):
        problems.append(f"keypoint 編號重複：{ids}")

    for k in kps:
        kid = k.get("id")
        for key in ("id", "text", "kind", "references"):
            if key not in k:
                problems.append(f"{kid} 缺少 {key}")
        if not k.get("references"):
            problems.append(f"{kid} 沒有任何 reference")
        for ref in k.get("references", []):
            if norm(ref.get("text", "")) not in src:
                problems.append(f"{kid} 的引文不在來源原文裡：{ref.get('text')!r}")
            for f in ("source_url", "source_kind", "as_of"):
                if f not in ref:
                    problems.append(f"{kid} 的 reference 缺少 {f}")
        if k.get("applies_if") and "value_check" not in k:
            problems.append(f"{kid} 是條件式 keypoint，要有 value_check 說明怎麼檢查")

    av = gold.get("allowed_values") or {}
    allowed = {e["value"] for e in av.get("extension", [])}
    for k in kps:
        if k.get("value_check") == "extension" and not set(k.get("acceptable_expressions", [])) <= allowed:
            problems.append(f"{k.get('id')} 的可接受寫法有不在 allowed_values 裡的分機")
    for p in av.get("extension_by_person", []):
        if p["extension"] not in allowed:
            problems.append(f"{p['name']} 的分機 {p['extension']} 不在允許集合")
        if norm(p["quote"]) not in src:
            problems.append(f"{p['name']} 的人員頁引句不在來源原文裡")
    for d in av.get("disallowed", []):
        if d["value"] in allowed:
            problems.append(f"禁止值 {d['value']} 同時在允許集合裡")
        if norm(d["reference"]["text"]) not in src:
            problems.append(f"禁止值 {d['value']} 的引文不在來源原文裡")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    path = Path(argv[1])
    if not path.exists():
        print(f"找不到 {path}", file=sys.stderr)
        return 2
    problems = validate_gold(path)
    if problems:
        print(f"FAIL {path}")
        for p in problems:
            print("  -", p)
        return 1
    print(f"PASS {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
