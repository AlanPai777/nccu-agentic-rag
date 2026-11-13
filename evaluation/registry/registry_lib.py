"""
evaluation/registry/registry_lib.py

單位登記表（registry.json）的讀取、驗證與比對函式。各題的 gold 只寫「用哪個單位、要什麼」，
由這裡展開成允許的寫法；登記表只維護一份（evaluation/registry/build_registry.py 建置）。

gold 的 keypoint 這樣引用：
  {"id": "K10", "kind": "hard", "value_check": "registry_who",
   "registry": {"office": "oic", "need": "who", "conditional": true}}
need：
  who        答案要有該單位任何一位的「姓名或職稱 + 分機」（姓名接受登記表記的任何寫法，姓氏＋小姐／先生也算），
             或該單位的代表線；姓名與分機對不上算 wrong
  floor      答案在該單位名稱同一行或前後 40 字內寫出樓層（"unit" 可指定組別，如國際教育組）；寫了別的樓層算 wrong
  form_link  答案要有登記表記的表單連結（"form"：表單編號）；"mention": "conditional" 時，答案沒提到這份表單就不適用
conditional  true：答案沒有提到該單位（任何別名）時，這個 keypoint 不適用、不計入

不上網。
"""
import json
import re
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
REGISTRY_JSON = HERE / "registry.json"
PAIR_WINDOW = 20      # 姓名（或職稱）與分機之間最多隔幾個字
FLOOR_WINDOW = 40     # 單位名稱與樓層之間最多隔幾個字
_EXT_RE = re.compile(r"(?<!\d)\d{5}(?!\d)")
NEEDS = ("who", "floor", "form_link")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


_TEXT: dict[str, str] = {}


def text_of(rel: str) -> str:
    """來源檔的純文字（相對 evaluation/registry/）；教務處頁面的 html 連結寫成 [文字](網址)。"""
    if rel not in _TEXT:
        raw = (HERE / rel).read_text(encoding="utf-8")
        if rel.endswith("aca_leave_page.html"):
            from gold_check import html_to_text
            _TEXT[rel] = html_to_text(raw)
        else:
            _TEXT[rel] = BeautifulSoup(raw, "html.parser").get_text(" ") if rel.endswith(".html") else raw
    return _TEXT[rel]


def load() -> dict:
    return json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))


# --- 驗證：登記表裡每一條引句都要在來源檔裡 --------------------------------------
def _sources(reg: dict):
    for okey, o in reg["offices"].items():
        for f in o["floors"]:
            for s in f["sources"]:
                yield f"{okey} 樓層 {f['value']}", s
        for ln in o["lines"]:
            for s in ln["sources"]:
                yield f"{okey} 代表線 {ln['value']}", s
        for e in o["staff"]:
            for key in ("names", "titles"):
                for n in e[key]:
                    for s in n["sources"]:
                        yield f"{okey} 分機 {e['ext']} {key} {n['value']}", s
            for s in e.get("ext_sources", []):
                yield f"{okey} 分機 {e['ext']} 分機", s
    for f in reg.get("forms", []):
        for n in f["names"]:
            for s in n["sources"]:
                yield f"表單 {f['id']} 名稱 {n['value']}", s
        for s in f["sources"]:
            yield f"表單 {f['id']}", s
        if f.get("live_check"):
            yield f"表單 {f['id']} 現場查證", f["live_check"]


def validate(reg: dict | None = None) -> list[str]:
    reg = reg or load()
    problems = []
    for what, s in _sources(reg):
        try:
            ok = norm(s["quote"]) in norm(text_of(s["file"]))
        except FileNotFoundError:
            problems.append(f"{what}：來源檔不存在 {s['file']}")
            continue
        if not ok:
            problems.append(f"{what}：{s['file']} 找不到「{s['quote']}」")
    return problems


# --- 展開 --------------------------------------------------------------------
def office(reg: dict, key: str) -> dict:
    return reg["offices"][key]


def office_aliases(o: dict) -> list[str]:
    return sorted({norm(a) for a in o["aliases"] + [o["name"]]}, key=len, reverse=True)


def name_strings(e: dict) -> set[str]:
    """登記表記的名字寫法（精確）。"""
    return {norm(n["value"]) for n in e["names"]}


def generated_strings(e: dict) -> set[str]:
    """可以和分機配成一對的所有寫法：記的名字、姓氏＋小姐／先生、職稱。"""
    out = name_strings(e)
    for n in e["names"]:
        v = norm(n["value"])
        if v:
            out |= {v[0] + "小姐", v[0] + "先生"}
    out |= {norm(t["value"]) for t in e["titles"] if len(norm(t["value"])) >= 2}
    return {s for s in out if s}


def rep_exts(o: dict) -> set[str]:
    """代表線裡的 5 位分機（如「02-29393091轉67729」→67729，「63016」→63016）。"""
    out = set()
    for ln in o["lines"]:
        m = re.search(r"(?<!\d)(\d{5})$", norm(ln["value"]))
        if m:
            out.add(m.group(1))
    return out


def ext_owners(reg: dict) -> dict[str, list[tuple[str, dict]]]:
    out: dict[str, list] = {}
    for okey, o in reg["offices"].items():
        for e in o["staff"]:
            if e["ext"]:
                out.setdefault(e["ext"], []).append((okey, e))
    return out


def allowed_for_judge(reg: dict, okey: str) -> dict:
    """給評審看的允許名單（人讀的摘要）。"""
    o = office(reg, okey)
    return {
        "單位": o["name"],
        "人員": [f"{'／'.join(sorted(name_strings(e))) or '（無姓名）'}（{'、'.join(sorted({norm(t['value']) for t in e['titles']}))}）分機 {e['ext'] or '無'}" for e in o["staff"]],
        "代表線": [ln["value"] for ln in o["lines"]],
        "樓層": [f"{f['value']}（{'、'.join(f['units'])}）" for f in o["floors"]],
    }


# --- 比對 --------------------------------------------------------------------
def mentions_office(answer: str, o: dict) -> bool:
    a = norm(answer)
    return any(al in a for al in office_aliases(o))


def _pairs(answer_norm: str, strings: set[str]):
    """(字串, 分機)：字串後 PAIR_WINDOW 字內的第一個分機。"""
    for s in strings:
        for m in re.finditer(re.escape(s), answer_norm):
            ext = _EXT_RE.search(answer_norm[m.end(): m.end() + PAIR_WINDOW + 5])
            if ext and ext.start() <= PAIR_WINDOW:
                yield s, ext.group()


def check_who(answer: str, reg: dict, okey: str) -> dict:
    o = office(reg, okey)
    a = norm(answer)
    owners = ext_owners(reg)
    hits, mismatches = [], []
    for e in o["staff"]:
        if not e["ext"]:
            continue
        for s in generated_strings(e):
            for m in re.finditer(re.escape(s), a):
                window = a[max(0, m.start() - PAIR_WINDOW): m.end() + PAIR_WINDOW + 5]
                if e["ext"] in window:
                    hits.append({"office": okey, "said": s, "ext": e["ext"]})
                    break
    # 分機對不上：登記表記的名字（精確寫法）後面緊接的分機，不是任何擁有這個名字的人的分機
    everyone = [(ok, e) for ok, oo in reg["offices"].items() for e in oo["staff"] if e["ext"]]
    by_name: dict[str, list] = {}
    for ok, e in everyone:
        for n in name_strings(e):
            by_name.setdefault(n, []).append((ok, e))
    for s, ext in _pairs(a, set(by_name)):
        holders = by_name[s]
        # 姓氏＋小姐／先生可能指任何一個單位的人（盧小姐可以是生僑組的盧誼甄，也可以是國合處的盧小姐）：只要有人用得到這個寫法且分機相符就不算錯
        owners_of_string = {e["ext"] for _, e in everyone if s in generated_strings(e)}
        if ext not in owners_of_string and any(ok == okey for ok, _ in holders):
            mismatches.append({"name": s, "said": ext, "expected": sorted({e["ext"] for _, e in holders})})
    rep = sorted(x for x in rep_exts(o) if re.search(rf"(?<!\d){x}(?!\d)", unicodedata.normalize("NFKC", answer or "")))
    known = set(owners) | {x for oo in reg["offices"].values() for x in rep_exts(oo)}
    unknown = sorted({x for x in _EXT_RE.findall(unicodedata.normalize("NFKC", answer or "")) if x not in known})
    row = {"office": okey, "matched": hits[:5], "representative_line": rep, "pair_mismatches": mismatches}
    if unknown:
        row["unknown_extensions"] = unknown
        row["needs_human_review"] = "答案有不在登記表的分機；若確認是合法分機，代表登記表漏了（例如系所分機不在登記表）"
    row["verdict"] = "wrong" if mismatches else ("hit" if hits or rep else "miss")
    return row


_FLOOR_RE = re.compile(r"(?:行政大樓)?(?:[一二三四五六七八九十]|\d{1,2})樓")


def check_floor(answer: str, reg: dict, okey: str, unit: str | None) -> dict:
    """樓層寫在單位名稱同一行（條列的一項）或前後 FLOOR_WINDOW 字內。寫了樓層但不是這個單位的任何一個樓層算 wrong。"""
    o = office(reg, okey)
    floors = [f for f in o["floors"] if unit is None or unit in f["units"]]
    exprs = [(norm(x), f["value"]) for f in floors for x in f["accepted"]]
    all_exprs = {norm(x) for f in o["floors"] for x in f["accepted"]}
    text = unicodedata.normalize("NFKC", answer or "")
    names = office_aliases(o) + ([norm(unit)] if unit else [])
    others = [al for k, oo in reg["offices"].items() if k != okey for al in office_aliases(oo)]
    nearby = []     # 單位名稱附近的文字：同一行裡前後 FLOOR_WINDOW 字；這一行沒有提到別的單位時，整行都算（條列的一項）
    for line in text.split("\n"):
        nl = norm(line)
        if not any(n in nl for n in names):
            continue
        if not any(al in nl for al in others):
            nearby.append(nl)
        for n in names:
            for m in re.finditer(re.escape(n), nl):
                nearby.append(nl[max(0, m.start() - FLOOR_WINDOW): m.end() + FLOOR_WINDOW])
    for chunk in nearby:
        for x, value in exprs:
            if x in chunk:
                return {"office": okey, "unit": unit, "matched": x, "floor": value, "verdict": "hit"}
    stated = sorted({m.group(0) for chunk in nearby for m in _FLOOR_RE.finditer(chunk)})
    expected = [f["value"] for f in floors]
    if stated and not any(norm(x) in all_exprs for x in stated) and not any(any(a in chunk for a in all_exprs) for chunk in nearby):
        return {"office": okey, "unit": unit, "expected": expected, "stated": stated, "verdict": "wrong"}
    return {"office": okey, "unit": unit, "expected": expected, "verdict": "miss"}


def form_mentioned(answer: str, form: dict) -> bool:
    a = norm(answer)
    names = [form["id"]] + [n["value"] for n in form["names"]]
    return any(norm(n) in a for n in names)


def check_form_link(answer: str, reg: dict, form_id: str, mention: str) -> dict:
    form = next(f for f in reg["forms"] if f["id"] == form_id)
    row = {"form": form_id, "url": form["url"]}
    if mention == "conditional" and not form_mentioned(answer, form):
        return {**row, "verdict": "not_applicable", "note": "答案沒有提到這份表單，不適用"}
    row["verdict"] = "hit" if norm(form["url"]) in norm(answer) else "miss"
    return row


def check_keypoint(kp: dict, answer: str, reg: dict) -> dict:
    """gold keypoint（含 registry 欄位）對一份答案的規則檢查；回傳 row，verdict 是 hit／miss／wrong／not_applicable。"""
    r = kp["registry"]
    if r["need"] == "form_link":
        return check_form_link(answer, reg, r["form"], r.get("mention", "always"))
    o = office(reg, r["office"])
    if r.get("conditional") and not mentions_office(answer, o):
        return {"office": r["office"], "verdict": "not_applicable", "note": "答案沒有提到這個單位，不適用，不計入"}
    if r["need"] == "who":
        return check_who(answer, reg, r["office"])
    return check_floor(answer, reg, r["office"], r.get("unit"))


def validate_keypoint_refs(kp: dict, reg: dict) -> list[str]:
    """gold_check 用：keypoint 的 registry 欄位要指到登記表裡真的有的東西。"""
    kid, r, problems = kp.get("id"), kp.get("registry"), []
    if r.get("need") not in NEEDS:
        return [f"{kid} 的 registry.need 要是 {NEEDS}"]
    if r["need"] == "form_link":
        if r.get("form") not in {f["id"] for f in reg.get("forms", [])}:
            problems.append(f"{kid} 的表單 {r.get('form')} 不在登記表")
        if r.get("mention", "always") not in ("always", "conditional"):
            problems.append(f"{kid} 的 mention 要是 always 或 conditional")
        return problems
    if r.get("office") not in reg["offices"]:
        return [f"{kid} 的單位 {r.get('office')} 不在登記表"]
    o = reg["offices"][r["office"]]
    if r["need"] == "floor":
        if not o["floors"]:
            problems.append(f"{kid}：{r['office']} 沒有樓層資料")
        if r.get("unit") and not any(r["unit"] in f["units"] for f in o["floors"]):
            problems.append(f"{kid}：{r['office']} 沒有組別 {r['unit']} 的樓層")
    if r["need"] == "who" and not (o["staff"] or o["lines"]):
        problems.append(f"{kid}：{r['office']} 沒有人員或代表線")
    return problems
