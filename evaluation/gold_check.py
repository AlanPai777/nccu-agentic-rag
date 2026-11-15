"""
evaluation/gold_check.py

gold.json 的機械檢查（不判斷內容寫得好不好，那要人讀）。回傳問題清單，空清單代表通過。
單元測試（evaluation/tests/test_gold_files.py）與 build-eval-gold skill 的驗證腳本共用這一份。

  - 必要欄位齊全、keypoint 編號不重複、每個 keypoint 有 references
  - 引用登記表的 keypoint（有 registry 欄位，見 registry/registry_lib.py）：指到登記表裡真有的單位／組別／表單，
    登記表本身每條引句再驗證一次；這類 keypoint 不需要自己的 references
  - 每個 reference 的 text 都是該題 sources/ 底下某份來源原文的子字串（空白與全半形正規化後）
  - 有 value_check 的 keypoint 與 allowed_values 一致；hard 的條件式 keypoint 有 applies_if 與 value_check（語意的條件式由評審判斷）
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

sys.path.insert(0, str(Path(__file__).resolve().parent / "registry"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry_lib  # noqa: E402
import reference_answer  # noqa: E402


def norm(s: str) -> str:
    return re.sub(r"[\s|\ue000-\uf8ff]+", "", unicodedata.normalize("NFKC", s or ""))  # 私用區字元（U+E000–U+F8FF，表單簽核欄的字型符號，肉眼看不到）不算內容，兩邊都拿掉


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


_EXT = re.compile(r"(?<!\d)\d{5,6}(?!\d)")


def keypoint_people(gold: dict, k: dict, reg: dict | None) -> list[dict] | None:
    """可替換的 keypoint 允許哪些人與分機：[{"names": {姓名…}, "ext": 分機}]；不是人員／分機型的 keypoint 回傳 None。"""
    spec = k.get("registry")
    if spec and spec.get("need") == "who":
        try:
            o = registry_lib.office(reg, spec["office"])
        except KeyError:
            return None
        return [{"names": {n["value"] for n in e["names"]}, "ext": e["ext"]} for e in o["staff"]]
    if k.get("value_check") == "extension":
        av = gold.get("allowed_values") or {}
        by_ext = {p["extension"]: p for p in av.get("extension_by_person", [])}
        out = []
        for e in av.get("extension", []):
            p = by_ext.get(e["value"])
            out.append({"names": {p["name"]} if p else set(), "ext": e["value"]})
        return out
    return None


def _fixed_corpus(gold: dict, reg: dict | None) -> str:
    """不可替換的片語必須出現在這些地方：keypoint 的文字、引句、可接受寫法，或登記表的連結、樓層、電話。"""
    parts = []
    for k in gold.get("keypoints", []):
        parts.append(k.get("text", ""))
        parts += [r.get("text", "") for r in k.get("references", []) or []]
        parts += k.get("acceptable_expressions", []) or []
        spec = k.get("registry")
        if spec and reg:
            try:
                if spec["need"] == "form_link":
                    f = next(x for x in reg["forms"] if x["id"] == spec["form"])
                    parts += [f["url"], f["id"]]
                elif spec["need"] == "floor":
                    parts += [a for f in registry_lib.office(reg, spec["office"])["floors"] for a in f["accepted"]]
                elif spec["need"] == "line":
                    parts += [ln["value"] for ln in registry_lib.office(reg, spec["office"])["lines"]]
            except (KeyError, StopIteration):
                pass
    return norm("\n".join(parts))


def _coverage(gold: dict, reg: dict | None, segs: list[dict]) -> list[str]:
    """每個 hard keypoint 的值都要出現在答案裡（漏寫就建置失敗）：可接受寫法之一、登記表人員的可替換片語、樓層、連結、電話。語意類由人檢查。"""
    plain = norm("".join(sg["v"] for sg in segs if sg["t"] != "opt"))
    digits = re.sub(r"\D", "", plain)
    rep_kps = {sg["kp"] for sg in segs if sg["t"] == "rep"}
    out = []
    for k in gold.get("keypoints", []):
        if k.get("kind") != "hard" or k.get("value_check") == "extension_pairs":
            continue
        kid, spec = k.get("id"), k.get("registry")
        if spec and reg:
            try:
                if spec["need"] == "who":
                    ok = kid in rep_kps
                elif spec["need"] == "floor":
                    ok = any(norm(a) in plain for f in registry_lib.office(reg, spec["office"])["floors"]
                             if not spec.get("unit") or spec["unit"] in f["units"] for a in f["accepted"])
                elif spec["need"] == "form_link":
                    ok = norm(next(x for x in reg["forms"] if x["id"] == spec["form"])["url"]) in plain
                elif spec["need"] == "line":
                    ln = next(x for x in registry_lib.office(reg, spec["office"])["lines"] if x.get("key") == spec.get("key"))
                    ok = re.sub(r"\D", "", ln["value"])[-8:] in digits
                else:
                    continue
            except (KeyError, StopIteration):
                continue
        elif k.get("value_check") == "extension":
            ok = kid in rep_kps
        elif k.get("acceptable_expressions"):
            ok = any(norm(a) in plain for a in k["acceptable_expressions"])
        else:
            continue
        if not ok:
            out.append(f"reference_answer：漏了 hard keypoint {kid} 的值（{k.get('text', '')[:40]}…）")
    return out


def check_reference_answer(gold: dict, reg: dict | None) -> list[str]:
    """reference_answer（畫面用的完整參考答案）的標記檢查：標記合法、不可替換的片語有依據、可替換的人員與分機對得上。"""
    text = gold.get("reference_answer")
    if text is None:
        return []
    try:
        segs = reference_answer.parse(text)
    except ValueError as e:
        return [f"reference_answer：{e}"]
    problems = _coverage(gold, reg, segs)
    kps = {k.get("id"): k for k in gold.get("keypoints", [])}
    corpus = None
    for sg in segs:
        if sg["t"] == "fixed":
            corpus = corpus if corpus is not None else _fixed_corpus(gold, reg)
            if norm(sg["v"]) not in corpus:
                problems.append(f"reference_answer：不可替換的片語沒有依據（不在任何 keypoint 的文字、引句或可接受寫法裡）：{sg['v']!r}")
        elif sg["t"] == "rep":
            k = kps.get(sg["kp"])
            people = keypoint_people(gold, k, reg) if k else None
            if people is None:
                problems.append(f"reference_answer：可替換的 {sg['kp']} 不是人員或分機型的 keypoint：{sg['v']!r}")
                continue
            exts = _EXT.findall(sg["v"])
            if not exts:
                problems.append(f"reference_answer：可替換的片語沒有分機：{sg['v']!r}")
            all_names = set().union(*(p["names"] for p in people))
            said = {n for n in all_names if n in sg["v"]}           # 片語裡寫了哪些登記的姓名
            for ext in exts:
                match = [p for p in people if p["ext"] == ext]
                if not match:
                    problems.append(f"reference_answer：分機 {ext} 不在 {sg['kp']} 的允許集合：{sg['v']!r}")
                elif said and not (said & set().union(*(p["names"] for p in match))):
                    problems.append(f"reference_answer：分機 {ext} 旁邊的姓名 {sorted(said)} 對不上登記的人員：{sg['v']!r}")
    return problems


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

    reg = None
    for k in kps:
        kid = k.get("id")
        if k.get("registry"):
            if reg is None:
                reg = registry_lib.load()
                problems += [f"登記表：{p}" for p in registry_lib.validate(reg)]
            for key in ("id", "text", "kind", "value_check"):
                if key not in k:
                    problems.append(f"{kid} 缺少 {key}")
            problems += registry_lib.validate_keypoint_refs(k, reg)
            continue
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
        if k.get("applies_if") and k.get("kind", "hard") == "hard" and "value_check" not in k:
            problems.append(f"{kid} 是條件式 keypoint，要有 value_check 說明怎麼檢查")   # 語意的條件式由評審依 applies_if 判斷

    # excluded（議題 F39）：標了就不進任何分母，所以一定要留下理由、日期與議題編號，才查得到為什麼不計分；也不能把全部 keypoint 都排除
    for k in kps:
        if "excluded" not in k:
            continue
        e = k["excluded"]
        if not isinstance(e, dict):
            problems.append(f"{k.get('id')} 的 excluded 要是物件（reason、since、issue），不能是 {e!r}")
            continue
        for f in ("reason", "since", "issue"):
            if not (isinstance(e.get(f), str) and e[f].strip()):
                problems.append(f"{k.get('id')} 的 excluded 缺少 {f}（不計分要留下理由、日期與議題編號）")
    if kps and all("excluded" in k for k in kps):
        problems.append("所有 keypoint 都標了 excluded：沒有任何 keypoint 可以計分")

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
    if gold.get("reference_answer") is not None and reg is None:
        reg = registry_lib.load()
    problems += check_reference_answer(gold, reg)
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
