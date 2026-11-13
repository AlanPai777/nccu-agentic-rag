"""
evaluation/registry/build_registry.py

建單位登記表 evaluation/registry/registry.json（人員、樓層、代表線；各題共用，只維護這一份）。

原則（沿用 evaluation/README.md）：抽取，不是生成。登記表裡每一個名字、職稱、分機、樓層、電話都附逐字引句，
引句要在來源檔裡找得到（NFKC 正規化、忽略空白）；名字與分機要在同一個表格列／同一張卡片。
任何一條驗證失敗就中止，不寫檔。來源檔都放在 evaluation/registry/sources/ 下，不需要上網。

每個人以分機為鍵，名字與職稱都記「寫法」，每個寫法帶它的所有來源（快照 snapshot、現場 live），答案符合任一寫法都算對：
  names[].form   full（全名）／surname_title（姓氏＋職稱或稱謂，如「王組長」「黃小姐」）
  status         both（快照與現場都有名字）／snapshot-only／live-only／title-only（沒有任何姓名，只有職稱）
來源種類：
  snapshot  語料快照（output/office_contacts_index.jsonl 有抓取時間；output/<子網域>/extracted_texts.jsonl 沒有時間，asof 記 "corpus"）
  live      2026-11-13 現場抓取（動態渲染的人員頁，或靜態 curl 的頁面；evaluation/registry/sources/live/live_check.md）

用法（在專案根目錄）：
  python evaluation/registry/build_registry.py
輸出：
  evaluation/registry/registry.json
  evaluation/registry/sources/snapshot/*.txt（引用到的快照原文複本）
"""
import json
import re
import sys
from urllib.parse import unquote
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from registry_lib import norm, text_of  # noqa: E402  比對與來源文字的函式只有一份（登記表的驗證也用它）

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LIVE_DIR = HERE / "sources" / "live"
SNAP_DIR = HERE / "sources" / "snapshot"
INDEX = ROOT / "output" / "office_contacts_index.jsonl"

EXT_RE = re.compile(r"^\d{5,6}$")     # 分機 5 位數；營繕組的技術人員是 6 位數（472013）
FIRST_ITEM = ("一、", "ㄧ、")  # 業務項目的第一項（有一份用的是注音符號 ㄧ）


class Problems(list):
    def add(self, msg: str) -> None:
        self.append(msg)


def src(kind: str, rel: str, asof: str, quote: str, problems: Problems, what: str) -> dict | None:
    """一個來源引用；引句找不到就記問題並回傳 None。"""
    if norm(quote) not in norm(text_of(rel)):
        problems.add(f"{what}：{rel} 找不到「{quote}」")
        return None
    return {"source": kind, "asof": asof, "file": rel, "quote": quote}


def add_form(items: list, form: str, value: str, source: dict | None, key: str = "form") -> None:
    """把來源加進 items 裡同形式同值的條目，沒有就新增。"""
    if source is None:
        return
    for it in items:
        if it[key] == form and it["value"] == value:
            if source not in it["sources"]:
                it["sources"].append(source)
            return
    items.append({key: form, "value": value, "sources": [source]})


def status_of(entry: dict) -> str:
    """both：快照與現場都有名字且姓氏一致（同一個人，可能是不同寫法）；snapshot-only／live-only：只有一邊有名字；
    changed：兩邊都有名字但姓氏不同（同一個分機換人了）；title-only：沒有任何姓名。"""
    if not entry["names"]:
        return "title-only"
    by_kind = {"snapshot": set(), "live": set()}
    for n in entry["names"]:
        for s in n["sources"]:
            by_kind[s["source"]].add(n["value"][0])
    if by_kind["snapshot"] and by_kind["live"]:
        return "both" if by_kind["snapshot"] & by_kind["live"] else "changed"
    return "snapshot-only" if by_kind["snapshot"] else "live-only"


def finish(entry: dict) -> dict:
    entry["status"] = status_of(entry)
    return entry


def snapshot_from_index(url: str, out_name: str) -> tuple[dict, str, str]:
    for line in INDEX.open(encoding="utf-8"):
        d = json.loads(line)
        if unquote(d.get("url", "")) == unquote(url):
            SNAP_DIR.mkdir(parents=True, exist_ok=True)
            rel = f"sources/snapshot/{out_name}"
            (HERE / rel).write_text(f"# url: {d['url']}\n# fetched_at: {d['fetched_at']}\n# 來源：output/office_contacts_index.jsonl\n\n{d['text']}\n", encoding="utf-8")
            return d, rel, d["fetched_at"][:10]
    raise SystemExit(f"索引裡找不到：{url}")


def snapshot_from_corpus(subdomain: str, url: str, out_name: str) -> tuple[dict, str]:
    for line in (ROOT / "output" / subdomain / "extracted_texts.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("url") == url:
            SNAP_DIR.mkdir(parents=True, exist_ok=True)
            rel = f"sources/snapshot/{out_name}"
            (HERE / rel).write_text(f"# url: {d['url']}\n# 來源：output/{subdomain}/extracted_texts.jsonl（無抓取時間）\n\n{d['text']}\n", encoding="utf-8")
            return d, rel
    raise SystemExit(f"語料裡找不到：{url}")


def live_asof(meta_file: str) -> str:
    return json.loads((LIVE_DIR / meta_file).read_text(encoding="utf-8"))["fetched_at"][:10]


LIVE_STATIC_ASOF = "2026-11-13"  # curl 靜態抓取，時間見 live_check.md


# --- 註冊組 ----------------------------------------------------------------
def parse_registrar_snapshot(text: str) -> list[dict]:
    """每一列從「一、」（業務項目第一項）開始，前兩行是職稱與姓名，其後（下一列開始前）第一個不加括號的五位數是分機。"""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    starts = [i for i, l in enumerate(lines) if l in FIRST_ITEM]
    rows = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        ext = next((x for x in lines[i + 1:end] if EXT_RE.match(x)), None)
        rows.append({"title": lines[i - 2], "name": lines[i - 1], "ext": ext})
    return rows


def parse_registrar_live(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = next(t for t in soup.find_all("table") if "分機" in t.get_text())
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 3:
            continue
        label = " ".join(cells[0].get_text(" ", strip=True).split())
        if not label or label == "姓名/職稱":
            continue
        ext_cell = " ".join(cells[-2].get_text(" ", strip=True).split())
        rows.append({"label": label, "ext": ext_cell if EXT_RE.match(ext_cell) else None})
    return rows


def build_registrar(problems: Problems) -> dict:
    what = "註冊組"
    rec, snap_rel, snap_asof = snapshot_from_index("https://aca.nccu.edu.tw/zh/%E4%BA%BA%E5%93%A1%E8%81%B7%E6%8E%8C-%E8%A8%BB%E5%86%8A", "aca_staff_registrar.txt")
    live_rel = "sources/live/aca_staff_registrar.rendered.html"
    l_asof = live_asof("aca_staff_registrar.render.json")
    snap_rows = parse_registrar_snapshot(rec["text"])
    live_rows = parse_registrar_live((HERE / live_rel).read_text(encoding="utf-8"))
    if len(snap_rows) != len(live_rows):
        problems.add(f"{what}：快照 {len(snap_rows)} 列，現場 {len(live_rows)} 列，列數不同")
    staff = []
    for k, (s, l) in enumerate(zip(snap_rows, live_rows), 1):
        w = f"{what}第 {k} 列"
        if s["ext"] != l["ext"]:
            problems.add(f"{w}：快照分機 {s['ext']}，現場分機 {l['ext']}")
        if norm(s["name"])[0] != norm(l["label"])[0]:
            problems.add(f"{w}：快照姓名 {s['name']} 與現場 {l['label']} 姓氏不同")
        e = {"ext": s["ext"] or l["ext"], "row": k, "names": [], "titles": []}
        add_form(e["names"], "full", norm(s["name"]), src("snapshot", snap_rel, snap_asof, s["name"], problems, w))
        add_form(e["names"], "surname_title", norm(l["label"]), src("live", live_rel, l_asof, l["label"], problems, w))
        add_form(e["titles"], "title", norm(s["title"]), src("snapshot", snap_rel, snap_asof, s["title"], problems, w), key="kind")
        add_form(e["titles"], "title", norm(l["label"])[1:], src("live", live_rel, l_asof, l["label"], problems, w), key="kind")
        if e["ext"]:
            e["ext_sources"] = [x for x in (src("snapshot", snap_rel, snap_asof, e["ext"], problems, w), src("live", live_rel, l_asof, e["ext"], problems, w)) if x]
        staff.append(finish(e))
    floor_snap = re.search(r"\d{5,6}[^\n]*?號\s*行政大樓四樓", rec["text"])
    floor_live = re.search(r"行政大樓四樓", text_of(live_rel))
    floors = []
    if floor_snap and floor_live:
        floors.append({"value": "行政大樓四樓", "accepted": ["行政大樓四樓", "四樓", "4樓"], "units": ["註冊組"], "sources": [
            src("snapshot", snap_rel, snap_asof, floor_snap.group(0), problems, what + "樓層"),
            src("live", live_rel, l_asof, "行政大樓四樓", problems, what + "樓層")]})
    else:
        problems.add(f"{what}樓層：快照或現場找不到行政大樓四樓")
    refund_snap = refund_page_snapshot()
    rep_quote = "行政大樓四樓教務處註冊組，代表分機 63279"
    lines = [{"kind": "代表分機（休退學相關問題）", "value": "63279", "sources": [x for x in (
        src("snapshot", refund_snap, "corpus", rep_quote, problems, what + "代表線"),
        src("live", "sources/live/osa_refund_standard.html", LIVE_STATIC_ASOF, rep_quote, problems, what + "代表線")) if x]}]
    return {"name": "註冊組", "aliases": ["教務處註冊組", "註冊組"], "parent": "教務處", "floors": floors, "lines": lines, "staff": staff}


# --- 生僑組 ----------------------------------------------------------------
def split_zh_en(s: str) -> tuple[str, str]:
    """「盧誼甄 LU, YI-CHEN」→（盧誼甄, LU, YI-CHEN）；「組長 Section Chief」→（組長, Section Chief）。"""
    m = re.match(r"^([^A-Za-z]*?)\s*([A-Za-z].*)?$", s.strip())
    return (m.group(1).strip(), (m.group(2) or "").strip())


def parse_soa_snapshot(text: str) -> list[dict]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    rows = []
    for i, l in enumerate(lines):
        if l == "職稱" and lines[i + 2] == "姓名" and lines[i + 4] == "分機":
            rows.append({"title": lines[i + 1], "name": lines[i + 3], "ext": lines[i + 5]})
    return rows


def parse_soa_live(html: str) -> list[dict]:
    rows = []
    for t in BeautifulSoup(html, "html.parser").find_all("table"):
        c = [" ".join(x.get_text(" ", strip=True).split()) for x in t.find_all(["td", "th"])]
        if c[:1] == ["職稱"] and "分機" in c:
            rows.append({"title": c[1], "name": c[3], "ext": c[5]})
    return rows


def build_soa(problems: Problems) -> dict:
    what = "生僑組"
    url = "https://osa.nccu.edu.tw/tw/生活事務暨僑生輔導組/關於我們/成員介紹"
    rec, snap_rel = snapshot_from_corpus("osa", url, "osa_staff_soa.txt")
    snap_asof = "corpus"
    live_rel = "sources/live/osa_staff_soa.rendered.html"
    l_asof = live_asof("osa_staff_soa.render.json")
    snap_rows, live_rows = parse_soa_snapshot(rec["text"]), parse_soa_live((HERE / live_rel).read_text(encoding="utf-8"))
    if len(snap_rows) != len(live_rows):
        problems.add(f"{what}：快照 {len(snap_rows)} 列，現場 {len(live_rows)} 列")
    staff = []
    for k, (s, l) in enumerate(zip(snap_rows, live_rows), 1):
        w = f"{what}第 {k} 列"
        if (s["ext"], norm(s["name"]), norm(s["title"])) != (l["ext"], norm(l["name"]), norm(l["title"])):
            problems.add(f"{w}：快照 {s} 與現場 {l} 不同")
        title_zh, title_en = split_zh_en(s["title"])
        name_zh, name_en = split_zh_en(s["name"])
        e = {"ext": s["ext"], "row": k, "names": [], "titles": [], "english": {"name": name_en, "title": title_en}}
        for kind, rel, asof, row in (("snapshot", snap_rel, snap_asof, s), ("live", live_rel, l_asof, l)):
            tz, _ = split_zh_en(row["title"])
            nz, _ = split_zh_en(row["name"])
            add_form(e["titles"], "title", tz, src(kind, rel, asof, tz, problems, w), key="kind")
            if nz != "待補":
                add_form(e["names"], "full", nz, src(kind, rel, asof, nz, problems, w))
            e.setdefault("ext_sources", []).append(src(kind, rel, asof, row["ext"], problems, w))
        e["ext_sources"] = [x for x in e["ext_sources"] if x]
        staff.append(e)
    # 姓名欄是「待補」的分機，職務代理人欄用「洪子茹（分機：62223）」寫出現任者；兩邊都有才收
    for e in staff:
        if not e["names"]:
            m = re.search(r"([一-鿿]{2,4})（分機：" + e["ext"] + "）", rec["text"])
            if m:
                q = m.group(0)
                add_form(e["names"], "full", m.group(1), src("snapshot", snap_rel, snap_asof, q, problems, what + e["ext"]))
                add_form(e["names"], "full", m.group(1), src("live", live_rel, l_asof, q, problems, what + e["ext"]))
                e["note"] = "姓名欄是「待補」；名字取自職務代理人欄的「姓名（分機：" + e["ext"] + "）」"
    staff = [finish(e) for e in staff]
    floors = [{"value": "行政大樓三樓", "accepted": ["行政大樓三樓", "三樓", "3樓"], "units": ["生僑組"], "sources": [
        src("snapshot", snap_rel, snap_asof, "行政大樓三樓", problems, what + "樓層"),
        src("live", live_rel, l_asof, "行政大樓三樓", problems, what + "樓層")]}]
    lines = [{"kind": "總機", "value": "63016", "sources": [
        src("snapshot", snap_rel, snap_asof, "總機 63016", problems, what + "總機"),
        src("live", live_rel, l_asof, "總機 63016", problems, what + "總機")]}]
    return {"name": "生僑組", "aliases": ["生活事務暨僑生輔導組", "學務處生僑組", "生僑組"], "parent": "學生事務處",
            "floors": floors, "lines": lines, "staff": staff}


# --- 國合處 ----------------------------------------------------------------
# 現場卡片沒有姓名的分機，另外用「姓名＋分機」同一句的頁面補全名（快照語料為主，現場靜態頁有同一句就一併記）
OIC_EXTRA_NAMES = [
    ("62058", "徐維勵", "Post/788", "大學部申請：徐維勵小姐（校內分機：62058）"),
    ("62510", "凌千喆", "Post/788", "研究所申請：凌千喆小姐（校內分機：62510）"),
    ("62040", "何芸婷", "Post/16017", "本案承辦人：何芸婷，分機62040"),
]


def build_oic(problems: Problems) -> dict:
    what = "國合處"
    rec, snap_rel, snap_asof = snapshot_from_index("https://oic.nccu.edu.tw/Category/596", "oic_category_596.txt")
    live_rel = "sources/live/oic_category_596.rendered.html"
    l_asof = live_asof("oic_category_596.render.json")
    soup = BeautifulSoup((HERE / live_rel).read_text(encoding="utf-8"), "html.parser")
    cards = soup.find_all(class_="staff-card")
    by_ext: dict[str, dict] = {}
    for k, c in enumerate(cards, 1):
        w = f"{what}第 {k} 張卡片"
        m = re.search(r"分機：(\d{5})", c.get_text())
        if not m:
            problems.add(f"{w}：沒有分機")
            continue
        ext = m.group(1)
        name_el, title_el = c.find(class_="staff-name"), c.find(class_="staff-title")
        name = name_el.get_text(strip=True) if name_el else ""
        title = title_el.get_text(strip=True) if title_el else ""
        e = by_ext.setdefault(ext, {"ext": ext, "row": len(by_ext) + 1, "names": [], "titles": [], "ext_sources": []})
        if name:
            form = "surname_title" if re.search(r"(小姐|先生)$", name) else "full"
            add_form(e["names"], form, name, src("live", live_rel, l_asof, name, problems, w))
        if title:
            add_form(e["titles"], "title", title, src("live", live_rel, l_asof, title, problems, w), key="kind")
        for x in (src("live", live_rel, l_asof, f"分機：{ext}", problems, w), src("snapshot", snap_rel, snap_asof, f"分機：{ext}", problems, w)):
            if x and x not in e["ext_sources"]:
                e["ext_sources"].append(x)
    snap_exts = set(re.findall(r"分機：(\d{5})", rec["text"]))
    if snap_exts != set(by_ext):
        problems.add(f"{what}：快照分機 {sorted(snap_exts ^ set(by_ext))} 與現場不一致")
    # 補全名：快照語料頁、現場靜態頁
    pages = {}
    for page, snap_file, live_file in (("Post/788", "oic_post_788.txt", "oic_post_788.html"), ("Post/16017", "oic_post_16017.txt", None)):
        _, rel = snapshot_from_corpus("oic", f"https://oic.nccu.edu.tw/{page}", snap_file)
        pages[page] = (rel, f"sources/live/{live_file}" if live_file else None)
    for ext, name, page, quote in OIC_EXTRA_NAMES:
        e = by_ext.get(ext)
        if e is None:
            problems.add(f"{what}：補全名的分機 {ext} 不在現場頁")
            continue
        w = f"{what}分機 {ext} 補全名"
        snap_page, live_page = pages[page]
        add_form(e["names"], "full", name, src("snapshot", snap_page, "corpus", quote, problems, w))
        if live_page:
            add_form(e["names"], "full", name, src("live", live_page, LIVE_STATIC_ASOF, quote, problems, w))
        for n in e["names"]:
            if n["form"] == "surname_title" and n["value"][0] != name[0]:
                problems.add(f"{w}：{name} 與現場 {n['value']} 姓氏不同")
    staff = [finish(e) for e in by_ext.values()]
    p800_snap, _ = snapshot_from_corpus("oic", "https://oic.nccu.edu.tw/Post/800", "oic_post_800.txt")
    s800, l800 = "sources/snapshot/oic_post_800.txt", "sources/live/oic_post_800.html"
    notice = "sources/live/aca_notice_115_1.pdf.txt"
    floors = []
    for value, acc, units, quote in (
        ("行政大樓八樓", ["行政大樓八樓", "行政大樓8樓", "八樓", "8樓"], ["國際教育組", "合作交流組", "海外辦公室"], "八樓—國際教育組、合作交流組、海外辦公室"),
        ("行政大樓七樓", ["行政大樓七樓", "行政大樓7樓", "七樓", "7樓"], ["大陸事務組", "發展策劃組"], "七樓—大陸事務組、發展策劃組"),
    ):
        srcs = [src("snapshot", s800, "corpus", quote, problems, what + "樓層"), src("live", l800, LIVE_STATIC_ASOF, quote, problems, what + "樓層")]
        if value == "行政大樓八樓":
            srcs.append(src("live", notice, LIVE_STATIC_ASOF, "國際合作事務處 (行政大樓八樓)", problems, what + "樓層"))
        floors.append({"value": value, "accepted": acc, "units": units, "sources": [x for x in srcs if x]})
    lines = [
        {"kind": "總機（註冊通知單的國際學生專線）", "value": "02-29393091轉67729", "sources": [src("live", notice, LIVE_STATIC_ASOF, "(聯絡電話：02-29393091轉67729)", problems, what + "專線")]},
        {"kind": "聯絡電話（國合處聯絡方式頁）", "value": "886-2-2938-7729", "sources": [
            src("snapshot", s800, "corpus", "聯絡電話：886-2-2938-7729", problems, what + "電話"),
            src("live", l800, LIVE_STATIC_ASOF, "聯絡電話：886-2-2938-7729", problems, what + "電話")]},
        {"kind": "頁尾電話（工作職掌頁）", "value": "886-2-29393091 #62040", "sources": [src("live", live_rel, l_asof, "電話 886-2-29393091 #62040", problems, what + "頁尾")]},
    ]
    for ln in lines:
        ln["sources"] = [x for x in ln["sources"] if x]
    return {"name": "國際合作事務處", "aliases": ["國合處", "國際合作事務處"], "parent": None, "floors": floors, "lines": lines, "staff": staff}


# --- 表單 ------------------------------------------------------------------
MOLTKE = "https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail="
LEAVE_PAGE = "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學"
TRANSFER_PAGE = "https://aca.nccu.edu.tw/zh/服務項目/學籍/轉系"
FORMS = [  # (編號, 在教務處頁面上的連結文字, 現場 302 標頭檔, 列出這份表單的頁面)
    ("QP-T01-03-04", "提早復學申請書", None, "leave"),
    ("QP-T01-02-05", "各項證明文件申辦委託書", "moltke_qp_t01_02_05.headers.txt", "leave"),
    ("QP-T01-03-02", "休學/保留學籍申請書", "moltke_QP-T01-03-02.headers.txt", "leave"),
    ("QP-T01-05-05", "碩士班轉系所申請書", "moltke_QP-T01-05-05.headers.txt", "transfer"),
    ("QP-T01-05-06", "碩士轉系所學分認定申請書", "moltke_QP-T01-05-06.headers.txt", "transfer"),
    ("QP-M03-01-05", "請下載填寫： 『退離宿暨退還「住宿保證金」申請表』", "moltke_QP-M03-01-05.headers.txt", "dorm", "osa"),
    ("QP-T01-03-08", "國立政治大學碩、博士班學生修讀雙主修輔系申請表", "moltke_QP-T01-03-08.headers.txt", "double"),
]
DOUBLE_PAGE = "https://aca.nccu.edu.tw/zh/服務項目/雙主修-輔系-學程/碩博士班雙修輔系"
EXIT_PAGE = "https://osa.nccu.edu.tw/tw/住宿輔導組/宿舍申請與床位資訊/退離宿程序"
# 頁面正文用的簡稱（逐字出現在列出這份表單的頁面裡），指的就是這份表單
FORM_ALIASES = {"QP-T01-02-05": ["委託書"], "QP-T01-05-05": ["轉系所申請書"], "QP-T01-05-06": ["學分認定申請書"],
                "QP-M03-01-05": ["離宿暨退還保證金申請表", "退離宿暨退還「住宿保證金」申請表", "離宿暨退還「住宿保證金」申請表"],
                "QP-T01-03-08": ["雙主修輔系申請表"]}


def build_forms(problems: Problems) -> list[dict]:
    _, page_rel = snapshot_from_corpus("aca", LEAVE_PAGE, "aca_leave_page.txt")
    live_page = "sources/live/aca_leave_page.html"
    _, tpage_rel = snapshot_from_corpus("aca", TRANSFER_PAGE, "aca_transfer_page.txt")
    tlive_page = "sources/live/aca_transfer_page.html"
    _, epage_rel = snapshot_from_corpus("osa", EXIT_PAGE, "osa_exit_procedure.txt")
    _, dpage_rel = snapshot_from_corpus("aca", DOUBLE_PAGE, "aca_double_major_page.txt")
    pages = {"leave": (page_rel, live_page), "transfer": (tpage_rel, tlive_page), "dorm": (epage_rel, "sources/live/osa_exit_procedure.html"),
             "double": (dpage_rel, "sources/live/aca_double_major_page.html")}
    recs = {}
    for sub in ("aca", "osa"):
        for line in (ROOT / "output" / sub / "extracted_supplementary.jsonl").open(encoding="utf-8"):
            d = json.loads(line)
            for fid, *_ in FORMS:
                if d["url"] == MOLTKE + fid:
                    recs[fid] = d
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    forms_rel = "sources/snapshot/moltke_forms.txt"
    (HERE / forms_rel).write_text("# 來源：output/aca 與 output/osa 的 extracted_supplementary.jsonl（無抓取時間）；每筆：網址、標題、全文\n\n" + "\n\n".join(
        f"url: {d['url']}\ntitle: {d['title']}\n{d['text']}" for d in recs.values()) + "\n", encoding="utf-8")
    out = []
    for fid, link_text, headers, which, *_ in FORMS:
        page_rel, live_page = pages[which]
        w = f"表單 {fid}"
        d = recs.get(fid)
        if d is None:
            problems.add(f"{w}：語料沒有這份表單")
            continue
        zh, _, en = d["title"].partition(" / ")
        link_quote = f"[{link_text}]({MOLTKE}{fid})"
        names = [zh] + ([en] if en else []) + FORM_ALIASES.get(fid, [])
        e = {"id": fid, "url": MOLTKE + fid, "names": [], "sources": [], "live_check": None}
        for n in names:
            basis = forms_rel if n in d["title"] else page_rel      # 名稱是表單標題的一部分就以表單為依據，否則以列出它的頁面為依據
            add_form(e["names"], "name", n, src("snapshot", basis, "corpus", n, problems, w), key="kind")
        e["sources"] = [x for x in (
            src("snapshot", forms_rel, "corpus", f"url: {MOLTKE}{fid}", problems, w),
            src("snapshot", page_rel, "corpus", link_quote, problems, w),
            src("live", live_page, LIVE_STATIC_ASOF, link_quote, problems, w)) if x]
        if headers:
            hrel = f"sources/live/{headers}"
            e["live_check"] = src("live", hrel, LIVE_STATIC_ASOF, f"Location: login.formservice?viewdetail={fid}", problems, w)
            if e["live_check"]:
                e["live_check"]["result"] = "302 轉到同一站台的登入頁，沒有跟隨；看不到表單內容，連結本身仍然有效"
        else:
            e["live_note"] = "沒有對這個網址送過現場請求（未經批准）；連結以教務處現場頁面（2026-11-13）上列出的為準"
        out.append(e)
    return out


# --- 第 5 題（休學）新增的單位：出納組、住宿組、原資中心、圖書館 -----------------------------------------
REFUND_URL = "https://osa.nccu.edu.tw/tw/生活事務暨僑生輔導組/學生生活事務/休退學暨研究生畢業退費/休-退-學退費標準"
FORM_SNAP = "sources/snapshot/moltke_forms.txt"      # QP-T01-03-02 的全文在 build_forms 裡寫入（單位樓層的依據是表單上的說明）


def refund_page_snapshot() -> str:
    _, rel = snapshot_from_corpus("osa", REFUND_URL, "osa_refund_standard.txt")
    return rel


def parse_dash_label_snapshot(text: str) -> list[dict]:
    """出納組：「劉桂芬 組長」「校內分機」「62120」。"""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    rows = []
    for i, l in enumerate(lines):
        if l == "校內分機" and EXT_RE.match(lines[i + 1]):
            name, _, title = lines[i - 1].replace("\xa0", " ").rpartition(" ")     # 姓名可能含空白（罕用字拆寫成「王 (禾+翟 )媗」），職稱是最後一段
            rows.append({"name": name.strip(), "title": title.strip(), "ext": lines[i + 1]})
    return rows


def parse_library(text: str) -> list[dict]:
    """圖書館典藏閱覽組：「左以文 組長」、業務項目（一、二、…）、「電話：(02)2939-3091 分機：67172」。"""
    lines = [l.strip().replace("\xa0", " ") for l in text.splitlines() if l.strip()]
    rows = []
    for i, l in enumerate(lines):
        if l.startswith("一、") and i > 0 and re.match(r"^[\u4e00-\u9fff]{2,4}\s+\S+$", lines[i - 1]):
            name, _, title = lines[i - 1].partition(" ")
            ext = next((m.group(1) for x in lines[i + 1:i + 40] for m in [re.search(r"分機：(\d{5})", x)] if m), None)
            rows.append({"name": name, "title": title.strip(), "ext": ext})
    return rows


def merge_people(problems: Problems, what: str, snap_rows, live_rows, snap_rel, snap_asof, live_rel, l_asof) -> list[dict]:
    """快照與現場各自解析成 (分機, 姓名, 職稱) 之後用分機合併：同一個分機兩邊都有名字就各記各的寫法（換人也照記，狀態 changed）。"""
    order, by_ext = [], {}
    for kind, rel, asof, rows in (("snapshot", snap_rel, snap_asof, snap_rows), ("live", live_rel, l_asof, live_rows)):
        for r in rows:
            ext = r.get("ext")
            key = ext or f"noext:{r['name']}"
            if key not in by_ext:
                by_ext[key] = {"ext": ext, "row": len(order) + 1, "names": [], "titles": [], "ext_sources": []}
                order.append(key)
            e = by_ext[key]
            w = f"{what} 分機 {ext or '無'}"
            nz, ne = split_zh_en(r["name"])
            tz, te = split_zh_en(r["title"])
            if nz and not re.search(r"待[補聘]", nz):
                form = "surname_title" if re.fullmatch(r"[\u4e00-\u9fff]小?[姐生]", nz) and nz[-2:] in ("小姐", "先生") else "full"
                add_form(e["names"], form, nz, src(kind, rel, asof, nz, problems, w))
            if tz:
                add_form(e["titles"], "title", tz, src(kind, rel, asof, tz, problems, w), key="kind")
            if ext:
                x = src(kind, rel, asof, ext, problems, w)
                if x:
                    e["ext_sources"].append(x)
    return [finish(by_ext[k]) for k in order]


def sources_for(kind_items, problems, what):
    return [x for x in kind_items if x]


def building_floor(problems, what, value, accepted, units, quotes):
    """quotes: [(kind, 相對路徑, as_of, 引句)]"""
    return {"value": value, "accepted": accepted, "units": units,
            "sources": [x for x in (src(k, r, a, q, problems, what + "樓層") for k, r, a, q in quotes) if x]}


GA_BASE = "https://nccuga.nccu.edu.tw/zh/%E4%BA%BA%E5%93%A1%E8%81%B7%E6%8E%8C%E9%81%B8%E5%96%AE/"
GA_FLOOR_QUOTE = "116臺北市文山區指南路二段64號 (行政大樓五樓)"
GA_UNITS = [   # (登記表鍵, 名稱, 別名, 現場檔名, 索引舊網址（沒有就是 None）, 新頁面網址的單位名稱)
    ("ga_dean", "總務長室", ["總務處長室", "總務長室"], "ga_dean", "https://dean.nccu.edu.tw/PageStaffing?fid=8353", "總務長室"),
    ("docu", "文書組", ["總務處文書組", "文書組"], "ga_docu", "https://docu.nccu.edu.tw/PageStaffing?fid=8372", "文書組"),
    ("aff", "事務組", ["總務處事務組", "事務組"], "ga_aff", "https://aff.nccu.edu.tw/PageStaffing?fid=8611", "事務組"),
    ("wealth", "財產組", ["總務處財產組", "財產組"], "ga_wealth", "https://wealth.nccu.edu.tw/PageStaffing?fid=8253", "財產組"),
    ("mend", "營繕組", ["總務處營繕組", "營繕組"], "ga_mend", "https://mend.nccu.edu.tw/PageStaffing?fid=8380", "營繕組"),
    ("cashier", "出納組", ["總務處出納組", "出納組"], "ga_cashier", "https://cashier.nccu.edu.tw/PageStaffing?fid=7994", "出納組"),
    ("safety", "環安組", ["環境保護與職業安全衛生組", "總務處環安組", "環安組"], "ga_safety", "https://environ.nccu.edu.tw/PageStaffing?fid=8473", "環安組"),
    ("planning", "校園規劃與發展組", ["校園規劃與發展組", "規劃組"], "ga_planning", "https://cpds.nccu.edu.tw/PageStaffing?fid=8465", "規劃組"),
]


def parse_ga_live(text: str) -> list[dict]:
    """總務處新人員頁（nccuga）：「姓名」「職稱」「校內分機」「62120」，姓名可能不顯示（接在「單位主管」「行政人員」之後）。"""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    rows = []
    for i, l in enumerate(lines):
        if l == "校內分機" and i + 1 < len(lines) and EXT_RE.match(lines[i + 1]):
            name = lines[i - 2] if i >= 2 and lines[i - 2] not in ("單位主管", "行政人員") else ""
            rows.append({"name": name, "title": lines[i - 1], "ext": lines[i + 1]})
    return rows


def index_line(url: str) -> int:
    for n, line in enumerate(INDEX.open(encoding="utf-8"), 1):
        if unquote(json.loads(line).get("url", "")) == unquote(url):
            return n
    return 0


def build_ga_unit(problems: Problems, key: str, name: str, aliases: list[str], live_name: str, old_url: str | None, page_name: str) -> dict:
    what = name
    live_rel = f"sources/live/{live_name}.rendered.html"
    meta = json.loads((LIVE_DIR / f"{live_name}.render.json").read_text(encoding="utf-8"))
    l_asof = meta["fetched_at"][:10]
    live_rows = parse_ga_live(BeautifulSoup((HERE / live_rel).read_text(encoding="utf-8"), "html.parser").get_text("\n"))
    snap_rows, snap_rel, snap_asof, line_no = [], "", "", 0
    if old_url:
        rec, snap_rel, snap_asof = snapshot_from_index(old_url, f"{live_name.replace('ga_', 'ga_old_')}.txt")
        snap_rows = parse_dash_label_snapshot(rec["text"])
        line_no = index_line(old_url)
    staff = merge_people(problems, what, snap_rows, live_rows, snap_rel, snap_asof, live_rel, l_asof)
    floors = [building_floor(problems, what, "行政大樓五樓", ["行政大樓五樓", "五樓", "5樓"], [name], [("live", live_rel, l_asof, GA_FLOOR_QUOTE)])]
    lines = []
    if key == "cashier":
        refund = refund_page_snapshot()
        floors[0]["sources"] += [x for x in (src("snapshot", FORM_SNAP, "corpus", "(行政大樓5樓) (確認學生帳戶)", problems, what + "樓層"),
                                             src("snapshot", refund, "corpus", "行政大樓五樓總務處出納組", problems, what + "樓層"),
                                             src("live", "sources/live/osa_refund_standard.html", LIVE_STATIC_ASOF, "行政大樓五樓總務處出納組", problems, what + "樓層")) if x]
        lines = [
            {"kind": "代表分機（帳戶登錄、入帳）", "value": "62123", "sources": [x for x in (
                src("snapshot", refund, "corpus", "總務處出納組，分機62123", problems, what + "代表線"),
                src("live", "sources/live/osa_refund_standard.html", LIVE_STATIC_ASOF, "總務處出納組，分機62123", problems, what + "代表線")) if x]},
            {"kind": "頁尾分機（總務處各組）", "value": "62120", "sources": [x for x in (
                src("live", "sources/live/cashier_nccuga_contact_info.html", LIVE_STATIC_ASOF, "出納組分機 62120", problems, what + "分機"),) if x]},
        ]
    new_url = GA_BASE + __import__("urllib.parse", fromlist=["quote"]).quote(page_name + "_")
    wtf = [{"role": "現在的官網頁面（現場來源）", "url": meta["url"], "checked": l_asof, "status": f"{meta['status']}，解析出 {len(live_rows)} 筆人員", "file": live_rel}]
    if old_url:
        old = {"role": "舊網址（索引裡的人員頁）", "url": old_url, "status": "未請求；索引網域與現站不同，推測已搬家，未驗證"}
        if key == "cashier":
            old["status"] = "301 轉到 https://nccuga.nccu.edu.tw/zh/PageStaffing?fid=7994，新站該路徑 404（2026-11-09，第 1 題查證）"
            old["evidence"] = src("live", "sources/live/cashier_redirects.md", "2026-11-09",
                                  "`301 Moved Permanently`，`Location: https://nccuga.nccu.edu.tw/zh/PageStaffing?fid=7994`", problems, what + "舊網址")
        wtf.append(old)
        wtf.append({"role": "快照（本機索引）", "file": "output/office_contacts_index.jsonl", "line": line_no, "fetched": snap_asof})
    else:
        wtf.append({"role": "快照（本機索引）", "status": "索引沒有這個單位"})
    out = {"name": name, "aliases": aliases, "parent": "總務處", "floors": floors, "lines": lines, "staff": staff, "where_to_find": wtf}
    if key == "cashier":
        out["note"] = "舊人員頁（cashier.nccu.edu.tw）已搬到 nccuga.nccu.edu.tw，人員以新頁面為現場來源（2026-11-13）"
    return out


def make_ga_builder(unit):
    key, name, aliases, live_name, old_url, page_name = unit
    return lambda problems: build_ga_unit(problems, key, name, aliases, live_name, old_url, page_name)


def build_dorm(problems: Problems) -> dict:
    what = "住宿組"
    rec, snap_rel, snap_asof = snapshot_from_index("https://osa.nccu.edu.tw/tw/住宿輔導組/關於我們/成員介紹", "osa_staff_dorm.txt")
    live_rel = "sources/live/osa_staff_dorm.rendered.html"
    l_asof = live_asof("osa_staff_dorm.render.json")
    staff = merge_people(problems, what, parse_soa_snapshot(rec["text"]), parse_soa_live((HERE / live_rel).read_text(encoding="utf-8")),
                         snap_rel, snap_asof, live_rel, l_asof)
    floors = [building_floor(problems, what, "行政大樓三樓", ["行政大樓三樓", "三樓", "3樓"], ["住宿組"], [
        ("snapshot", FORM_SNAP, "corpus", "限住宿生(行政大樓 3 樓)"),
        ("live", live_rel, l_asof, "行政大樓三樓")])]
    lines = [{"kind": "總機", "value": "63252", "sources": [x for x in (
        src("snapshot", snap_rel, snap_asof, "住宿組總機 63252", problems, what + "總機"),
        src("live", live_rel, l_asof, "住宿組總機 63252", problems, what + "總機")) if x]}]
    return {"name": "住宿輔導組", "aliases": ["住宿輔導組", "住宿組"], "parent": "學生事務處", "floors": floors, "lines": lines, "staff": staff}


def build_indigenous(problems: Problems) -> dict:
    what = "原資中心"
    rec, snap_rel, snap_asof = snapshot_from_index("https://osa.nccu.edu.tw/tw/原資中心/關於我們-原資中心/成員介紹-原資中心", "osa_staff_indigenous.txt")
    live_rel = "sources/live/osa_staff_indigenous.rendered.html"
    l_asof = live_asof("osa_staff_indigenous.render.json")
    staff = merge_people(problems, what, parse_soa_snapshot(rec["text"]), parse_soa_live((HERE / live_rel).read_text(encoding="utf-8")),
                         snap_rel, snap_asof, live_rel, l_asof)
    floors = [building_floor(problems, what, "行政大樓三樓", ["行政大樓三樓", "三樓", "3樓"], ["原資中心"], [
        ("snapshot", FORM_SNAP, "corpus", "(行政大樓 3 樓) (僑生、港澳生、陸生至生僑組) (原住民族籍學生至原資中心)"),
        ("live", live_rel, l_asof, "行政大樓三樓")])]
    return {"name": "原住民族學生資源中心", "aliases": ["原住民族學生資源中心", "原資中心"], "parent": "學生事務處", "floors": floors, "lines": [], "staff": staff}


LIB_CONTACT_URL = "https://www.lib.nccu.edu.tw/p/404-1000-312.php?Lang=zh-tw"
ACA_LIB_URL = "https://aca.nccu.edu.tw/zh/學士班/圖書資源-學士班"
STAT_PHONES_URL = "https://stat.nccu.edu.tw/uploads/asset/data/6a6c5abf6c08dbf03ce2a188/常用行政電話一覽表.pdf"


def build_library(problems: Problems) -> dict:
    what = "圖書館典藏閱覽組"
    rec, snap_rel, snap_asof = snapshot_from_index("https://www.lib.nccu.edu.tw/p/404-1000-537.php?Lang=zh-tw", "lib_staff_circulation.txt")
    live_rel = "sources/live/lib_staff_circulation.rendered.html"
    l_asof = live_asof("lib_staff_circulation.render.json")
    live_text = BeautifulSoup((HERE / live_rel).read_text(encoding="utf-8"), "html.parser").get_text("\n")
    staff = merge_people(problems, what, parse_library(rec["text"]), parse_library(live_text), snap_rel, snap_asof, live_rel, l_asof)
    # 圖書館的電話（第 6 題）：各組聯絡資訊頁（快照與現場）、教務處「圖書資源」頁、統計系「常用行政電話」
    _, c_snap, c_asof = snapshot_from_index(LIB_CONTACT_URL, "lib_contact_units.txt")
    c_live = "sources/live/lib_contact_units.rendered.html"
    c_live_asof = live_asof("lib_contact_units.render.json")
    _, aca_rel = snapshot_from_corpus("aca", ACA_LIB_URL, "aca_library_resource.txt")
    _, stat_rel = snapshot_from_corpus("stat", STAT_PHONES_URL, "stat_admin_phones.txt")

    def line(key, kind, value, quotes, labels=()):
        """quotes: [(來源種類, 檔案, as_of, 引句)]；labels：答案裡提到這條電話時會出現的字眼（比對電話寫錯時用，見 registry_lib.check_line）"""
        return {"key": key, "kind": kind, "value": value, "labels": list(labels),
                "sources": [x for x in (src(k, r, a, q, problems, what + "電話 " + value) for k, r, a, q in quotes) if x]}

    head = "總圖 63222，綜圖 50107，商圖 84006，傳圖 67152"
    both = lambda q: [("snapshot", c_snap, c_asof, q), ("live", c_live, c_live_asof, q)]      # noqa: E731
    lines = [
        line("main_ext", "總圖（中正館流通櫃臺、典藏閱覽組）校內分機", "63222",
             both("總圖 63222") + [("snapshot", aca_rel, "corpus", "中正館流通櫃臺 (02)2939-3091轉分機63222")],
             ["總圖", "中正", "流通", "借還", "典藏閱覽"]),
        line("direct", "典藏閱覽組直撥電話（聯絡頁表格顯示的；該格連結的 tel: 目標是學校總機，與顯示不同）", "(02)2938-7878",
             [("snapshot", c_snap, c_asof, "[(02)2938-7878](tel:+886229393091)"), ("live", c_live, c_live_asof, "(02)2938-7878"),
              ("snapshot", stat_rel, "corpus", "圖書館 | (02)2938-7878")], ["直撥", "典藏閱覽", "總圖", "中正", "流通", "借還"]),
        line("switchboard", "政大總機", "(02)29393091", both("政大總機：(02)29393091"), ["總機"]),
        line("zonghe_ext", "綜圖校內分機", "50107", both(head) + [("snapshot", aca_rel, "corpus", "綜圖 (02)2939-3091轉分機50107")], ["綜圖"]),
        line("shang_ext", "商圖校內分機", "84006", both(head) + [("snapshot", aca_rel, "corpus", "商圖 (02)2939-3091轉分機84006")], ["商圖"]),
        line("chuan_ext", "傳圖校內分機", "67152", both(head) + [("snapshot", aca_rel, "corpus", "傳圖 (02)2939-3091轉分機67152")], ["傳圖"]),
        line("daxian", "達賢圖", "(02)82377017", both("達賢圖：(02)82377017"), ["達賢"]),
    ]
    return {"name": "圖書館典藏閱覽組", "aliases": ["圖書館", "典藏閱覽組", "總圖或分館借還書櫃檯"], "parent": "圖書館", "floors": [], "lines": lines, "staff": staff,
            "note": "申請書只寫「總圖或分館借還書櫃檯」，沒有樓層；人員只記典藏閱覽組（流通業務）；電話線來自各組聯絡資訊頁"}


OFFICES = {"registrar": build_registrar, "soa": build_soa, "oic": build_oic,
           **{u[0]: make_ga_builder(u) for u in GA_UNITS},
           "dorm": build_dorm, "indigenous": build_indigenous, "library": build_library}


def main() -> int:
    problems = Problems()
    forms = build_forms(problems)       # 先建表單：它會寫出表單全文的快照複本，單位的樓層引句要讀
    registry = {"version": 1, "offices": {key: fn(problems) for key, fn in OFFICES.items()}, "forms": forms}
    if problems:
        print("驗證失敗，沒有寫檔：")
        for p in problems:
            print("  -", p)
        return 1
    out = HERE / "registry.json"
    out.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for o in registry["offices"].values():
        c = {}
        for s in o["staff"]:
            c[s["status"]] = c.get(s["status"], 0) + 1
        print(f"{o['name']}：{len(o['staff'])} 筆 {c}，樓層 {[f['value'] for f in o['floors']]}，代表線 {len(o['lines'])} 條")
    print(f"表單：{[f['id'] for f in registry['forms']]}")
    print(f"→ {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
