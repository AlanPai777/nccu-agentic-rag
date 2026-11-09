"""
evaluation/cashier_contact/build_gold.py

建「出納組電話幾號」的 gold（phase_k_evaluation_design.md 第 5 節的格式）。

原則（沿用 evaluation/README.md）：抽取，不是生成。gold 裡每個 reference 的 text
必須逐字出現在來源原文裡；寫檔前逐條驗證（忽略空白，做 Unicode 相容正規化），
任何一條找不到就中止，不寫檔。

來源：
  - snapshot：output/ 的 2026-08 快照（讀 output/*/extracted_texts.jsonl，不上網）
  - live：sources/live/ 的 2026-11-09 現場頁面（已存檔，本腳本不上網）

用法（在專案根目錄）：
  python evaluation/cashier_contact/build_gold.py
輸出：
  evaluation/cashier_contact/gold.json
  evaluation/cashier_contact/sources/snapshot/*.txt（引用到的快照原文複本）
"""
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LIVE_DIR = HERE / "sources" / "live"
SNAP_DIR = HERE / "sources" / "snapshot"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"[\s|]+", "", s)


def live_text(name: str) -> str:
    raw = (LIVE_DIR / name).read_text(encoding="utf-8", errors="ignore")
    raw = re.sub(r"(?s)<(script|style).*?</\1>", "", raw)
    raw = re.sub(r"<[^>]+>", "\n", raw)
    return html.unescape(raw)


def snapshot_record(subdomain: str, url: str) -> dict:
    path = ROOT / "output" / subdomain / "extracted_texts.jsonl"
    for line in path.open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("url") == url:
            return d
    raise SystemExit(f"找不到快照頁面：{url}（{path}）")


# --- 來源定義 -----------------------------------------------------------
SNAP = {
    "S1": ("cashier", "https://cashier.nccu.edu.tw/", "cashier_home.txt"),
    "S2": ("cashier", "https://cashier.nccu.edu.tw/PageStaffing?fid=7994", "cashier_staffing_fid7994.txt"),
    "S3": ("aca", "https://aca.nccu.edu.tw/db/upload/1142註冊通知單中文版.pdf", "aca_registration_notice_1142.txt"),
    "S4": ("osa", "https://osa.nccu.edu.tw/tw/faq", "osa_faq.txt"),
    "S5": ("politics", "https://politics.nccu.edu.tw/PageDoc?fid=619", "politics_pagedoc_fid619.txt"),
}
LIVE = {
    "L1": ("https://nccuga.nccu.edu.tw/zh/", "nccuga_home.html"),
    "L2": ("https://nccuga.nccu.edu.tw/zh/各組服務項目/出納組?view=default", "nccuga_cashier_service.html"),
    "L3": ("https://nccuga.nccu.edu.tw/zh/關於我們/聯絡資訊", "nccuga_contact_info.html"),
}

SNAP_AS_OF = "2026-08（output/ 快照；校務頁面 2026-08-19）"
LIVE_AS_OF = "2026-11-09（現場）"

# --- gold 內容 ----------------------------------------------------------
REFS_K1 = [
    {"text": "總務處出納組 (02)2939-3091分機62120", "src": "S1", "kind": "snapshot"},
    {"text": "出納組分機 62120", "src": "L1", "kind": "live"},
    {"text": "出納組分機 62120", "src": "L2", "kind": "live"},
]

# 出納組人員頁（快照）排版：「代理人 X Y 職稱 校內分機 N」，Y 是本人、N 是 Y 的分機
# （與 contact_node 解析出的名單一致）。(分機, 姓名, 職稱, 人員頁引句)
PEOPLE = [
    ("62120", "劉桂芬", "組長", "劉桂芬 組長 校內分機 62120"),
    ("62172", "徐士雲", "編審", "徐士雲 編審 校內分機 62172"),
    ("62125", "張錦虹", "組員", "張錦虹 組員 校內分機 62125"),
    ("62122", "江幸霓", "組員", "江幸霓 組員 校內分機 62122"),
    ("62126", "張佩雯", "行政專員", "張佩雯 行政專員 校內分機 62126"),
    ("62127", "蕭毓璇", "行政專員", "蕭毓璇 行政專員 校內分機 62127"),
    ("62173", "鄭雅玲", "一級行政組員", "鄭雅玲 一級行政組員 校內分機 62173"),
    ("62121", "吳慧玲", "一級行政組員", "吳慧玲 一級行政組員 校內分機 62121"),
    ("62123", "余淑娟", "一級行政組員", "余淑娟 一級行政組員 校內分機 62123"),
    ("63071", "王(禾+翟)媗", "行政組員", "行政組員 校內分機 63071"),
    ("62124", "林瓊蓮", "兼任助理", "林瓊蓮 兼任助理 校內分機 62124"),
]
# 每個允許分機的補充依據（頁尾、註冊通知單、學務處 FAQ），逐字驗證
EXTRA_QUOTES = {
    ("62120", "S1"): "(02)2939-3091分機62120",
    ("62120", "L1"): "出納組分機 62120",
    ("62119", "S3"): "62119-62123、62125-62127、62172、62173",
    ("62123", "S3"): "出納組代表分機 62123",
    ("62123", "S4"): "出納組，校內分機62123",
}
EXT_NOTES = {
    "62120": "頁尾標示的出納組分機（快照與 2026-11-09 現場皆確認）；人員頁為組長劉桂芬",
    "62123": "人員頁為一級行政組員余淑娟；另為帳號登錄、退費、助學金入帳等問題的出納組代表分機（註冊通知單、學務處 FAQ）",
    "62119": "註冊通知單「出納組聯絡電話」範圍「62119-62123」的起點；人員頁未列此號碼，不屬於任何一位人員",
}
EXT_ORDER = ["62119", "62120", "62121", "62122", "62123", "62124", "62125", "62126", "62127", "62172", "62173", "63071"]
EXT_QUOTES = {}


DISALLOWED = [
    {
        "value": "62095",
        "reason": "總務處（整個單位）的分機，不是出納組；2026-11-09 現場「聯絡資訊」頁本文所寫",
        "reference": {"text": "總務處 (02)2939-3091 分機62095", "src": "L3", "kind": "live"},
    }
]


def main():
    # 1. 取來源文字
    snap_texts = {}
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    for key, (sub, url, fname) in SNAP.items():
        rec = snapshot_record(sub, url)
        snap_texts[key] = rec["text"]
        (SNAP_DIR / fname).write_text(
            f"# 來源：{url}\n# 檔案：output/{sub}/extracted_texts.jsonl\n# 資料日期：{SNAP_AS_OF}\n"
            f"# 以下為該筆記錄的 text 欄位全文（逐字複本）\n\n{rec['text']}\n",
            encoding="utf-8",
        )
    live_texts = {k: live_text(f) for k, (_, f) in LIVE.items()}
    src_text = {**snap_texts, **live_texts}
    src_url = {**{k: v[1] for k, v in SNAP.items()}, **{k: v[0] for k, v in LIVE.items()}}

    # 2. 驗證所有引句都逐字在來源裡（空白正規化）
    def check(text, src, what):
        if norm(text) not in norm(src_text[src]):
            raise SystemExit(f"找不到原文，中止：[{what}] {text!r} 不在 {src}（{src_url[src]}）")

    for r in REFS_K1:
        check(r["text"], r["src"], "K1.references")
    for ext, name, title, quote in PEOPLE:
        check(quote, "S2", f"person {name} {ext}")
    for (val, src), q in EXTRA_QUOTES.items():
        check(q, src, f"allowed {val}")
    for d in DISALLOWED:
        check(d["reference"]["text"], d["reference"]["src"], f"disallowed {d['value']}")

    person_by_ext = {e: (n, t, q) for e, n, t, q in PEOPLE}

    def ext_entry(v):
        sources, status = [], "snapshot_only"
        if v in person_by_ext:
            n, t, q = person_by_ext[v]
            sources.append({"source_url": src_url["S2"], "quote": q, "person": f"{n}（{t}）"})
        for (val, s_), q in EXTRA_QUOTES.items():
            if val == v:
                sources.append({"source_url": src_url[s_], "quote": q})
                if s_.startswith("L"):
                    status = "live_confirmed"
        return {"value": v, "status": status, "note": EXT_NOTES.get(v, ""), "sources": sources}

    # 62119 只有範圍記號、人員頁沒有；其餘 11 個分機都在人員頁個別列出
    assert set(person_by_ext) | {"62119"} == set(EXT_ORDER), "EXT_ORDER 與 PEOPLE 不一致"

    def ref(r):
        return {
            "text": r["text"],
            "source_url": src_url[r["src"]],
            "source_kind": r["kind"],
            "as_of": SNAP_AS_OF if r["kind"] == "snapshot" else LIVE_AS_OF,
        }

    gold = {
        "query_id": "cashier_contact",
        "query": "出納組電話幾號",
        "query_variants": ["出納組的電話是幾號"],
        "query_type": "contact",
        "data_as_of": {
            "snapshot": SNAP_AS_OF,
            "live": LIVE_AS_OF + "；只確認分機 62120，其餘分機現場無法確認",
        },
        "content": "出納組電話為 (02)2939-3091，分機 62120。",
        "keypoints": [
            {
                "id": "K1",
                "text": "給出出納組的電話分機（允許集合內任一個皆可）；官網頁尾標示為 (02)2939-3091 分機 62120",
                "required": True,
                "kind": "hard",
                "references": [ref(r) for r in REFS_K1],
                # 設計決定（2026-11-09）：答案寫允許集合內任一分機都算對，不限 62120
                "acceptable_expressions": EXT_ORDER,
            }
        ],
        "allowed_values": {
            "extension": [ext_entry(v) for v in EXT_ORDER],
            # 人名與分機成對：答案若同時寫人名與分機，這一對必須對得上
            "extension_by_person": [
                {"name": n, "title": t, "extension": e,
                 "source_url": src_url["S2"], "quote": q}
                for e, n, t, q in PEOPLE
            ],
            "disallowed": [
                {"value": d["value"], "reason": d["reason"], "reference": ref(d["reference"])}
                for d in DISALLOWED
            ],
        },
        "source_conflicts": (
            "無實質矛盾：62120 是頁尾標示的出納組電話（快照與 2026-11-09 現場皆確認），"
            "其餘為議題性代表分機或承辦分機。CLAUDE.md 先前記載的「62123 與 62120 語料不一致」"
            "依來源原文判讀是用途不同，不是同一問題的兩個答案。"
        ),
        "notes": [
            "出納組網站 cashier.nccu.edu.tw 於 2026-11-09 已 301 轉到 nccuga.nccu.edu.tw；"
            "舊人員頁 fid=7994 在新站為 404，詳見 sources/live/redirects.md",
            "人員頁排版為「代理人 X Y 職稱 校內分機 N」，Y 是本人、N 是 Y 的分機（與 contact_node 解析結果一致）；"
            "11 個人員分機全部在快照人員頁個別列出，現場只確認 62120",
            "62119 只出現在註冊通知單的範圍記號，人員頁沒有這個號碼",
            "題目只問電話，不涉及個人；extension_by_person 只在答案同時寫人名與分機時用來檢查成對",
            "K1 採「允許集合內任一分機皆可」（設計決定 2026-11-09）；頁尾標示的 62120 是官網的出納組電話，其餘為承辦人或議題性代表分機",
        ],
    }
    out = HERE / "gold.json"
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已寫入 {out.relative_to(ROOT)}")
    print(f"快照原文複本：{len(SNAP)} 份（{SNAP_DIR.relative_to(ROOT)}）")
    print(f"驗證通過：K1 references {len(REFS_K1)} 條、人員分機 {len(PEOPLE)} 筆、"
          f"補充依據 {len(EXTRA_QUOTES)} 條、禁止值 {len(DISALLOWED)} 條")


if __name__ == "__main__":
    sys.exit(main())
