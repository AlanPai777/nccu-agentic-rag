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

# 每個允許分機的依據（只列有逐字原文的；從範圍記號推得者另註）
EXT = [
    ("62120", "live_confirmed", "頁尾標示的出納組分機；快照人員頁為組長劉桂芬分機", ["S1", "L1"]),
    ("62119", "snapshot_only", "註冊通知單「出納組聯絡電話」範圍的起點", ["S3"]),
    ("62121", "snapshot_only_inferred_from_range", "由範圍記號「62119-62123」推得，非個別列出", ["S3"]),
    ("62122", "snapshot_only_inferred_from_range", "由範圍記號「62119-62123」推得；另見其他舊註冊通知單單獨出現", ["S3"]),
    ("62123", "snapshot_only", "帳號登錄、退費、助學金入帳等問題的出納組代表分機（註冊通知單、學務處 FAQ）；快照人員頁為一級行政組員余淑娟（排版有歧義）", ["S3", "S4", "S2"]),
    ("62125", "snapshot_only", "註冊通知單範圍「62125-62127」的起點", ["S3"]),
    ("62126", "snapshot_only_inferred_from_range", "由範圍記號「62125-62127」推得，非個別列出", ["S3"]),
    ("62127", "snapshot_only", "註冊通知單範圍「62125-62127」的終點", ["S3"]),
    ("62172", "snapshot_only", "註冊通知單列出的出納組聯絡分機", ["S3"]),
    ("62173", "snapshot_only", "註冊通知單列出的出納組聯絡分機", ["S3"]),
]
EXT_QUOTES = {  # 用來驗證「依據」確實存在的原文片段（逐字）
    ("62120", "S1"): "(02)2939-3091分機62120",
    ("62120", "L1"): "出納組分機 62120",
    ("62119", "S3"): "62119-62123、62125-62127、62172、62173",
    ("62121", "S3"): "62119-62123",
    ("62122", "S3"): "62119-62123",
    ("62123", "S3"): "出納組代表分機 62123",
    ("62123", "S4"): "出納組，校內分機62123",
    ("62123", "S2"): "62123",
    ("62125", "S3"): "62125-62127",
    ("62126", "S3"): "62125-62127",
    ("62127", "S3"): "62125-62127",
    ("62172", "S3"): "62172",
    ("62173", "S3"): "62173",
}
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

    # 2. 驗證 L3 的「62095」引句也要在 live 文字裡（空白正規化）
    def check(text, src, what):
        if norm(text) not in norm(src_text[src]):
            raise SystemExit(f"找不到原文，中止：[{what}] {text!r} 不在 {src}（{src_url[src]}）")

    for r in REFS_K1:
        check(r["text"], r["src"], "K1.references")
    for (val, src), q in EXT_QUOTES.items():
        check(q, src, f"allowed {val}")
    for d in DISALLOWED:
        check(d["reference"]["text"], d["reference"]["src"], f"disallowed {d['value']}")

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
                "text": "電話為 (02)2939-3091 分機 62120",
                "required": True,
                "kind": "hard",
                "references": [ref(r) for r in REFS_K1],
                "acceptable_expressions": ["62120"],
            }
        ],
        "allowed_values": {
            "extension": [
                {
                    "value": v,
                    "status": st,
                    "note": note,
                    "sources": [
                        {"source_url": src_url[s], "quote": EXT_QUOTES[(v, s)]}
                        for s in srcs
                        if (v, s) in EXT_QUOTES
                    ],
                }
                for v, st, note, srcs in EXT
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
            "62121、62122、62126 由範圍記號推得（status 標 inferred_from_range），非來源個別列出",
            "快照人員頁中 62123 屬於余淑娟或代理人欄位的排版有歧義，未據此認定人員",
            "題目只問電話，不涉及個人；人員不列入 gold",
        ],
    }
    out = HERE / "gold.json"
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已寫入 {out.relative_to(ROOT)}")
    print(f"快照原文複本：{len(SNAP)} 份（{SNAP_DIR.relative_to(ROOT)}）")
    print(f"驗證通過：K1 references {len(REFS_K1)} 條、允許分機依據 {len(EXT_QUOTES)} 條、禁止值 {len(DISALLOWED)} 條")


if __name__ == "__main__":
    sys.exit(main())
