"""
evaluation/leave_form_download/build_gold.py

建「休學申請表在哪裡下載」的 gold（phase_k_evaluation_design.md 第 5 節的格式；資源類題目）。

原則（沿用 evaluation/README.md）：抽取，不是生成。gold 裡每個 reference 的 text
必須逐字出現在來源原文裡；寫檔前逐條驗證（忽略空白，做 Unicode 相容正規化），
任何一條找不到就中止，不寫檔。

來源：
  - snapshot：output/aca/extracted_texts.jsonl（兩個教務處頁面）與 output/aca/extracted_supplementary.jsonl
    （moltke 上的表單本身），不上網
  - live：sources/live/ 的 2026-11-13 現場頁面（已存檔，本腳本不上網）。現場 HTML 的連結寫成 [文字](網址)，
    與快照裡的 markdown 連結同形（evaluation/gold_check.py 的 html_to_text）

用法（在專案根目錄）：
  python evaluation/leave_form_download/build_gold.py
輸出：
  evaluation/leave_form_download/gold.json
  evaluation/leave_form_download/sources/snapshot/*.txt（引用到的快照原文複本）
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "evaluation"))
from gold_check import html_to_text  # noqa: E402

LIVE_DIR = HERE / "sources" / "live"
SNAP_DIR = HERE / "sources" / "snapshot"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"[\s|]+", "", s)


def snapshot_record(file_name: str, url: str) -> dict:
    path = ROOT / "output" / "aca" / file_name
    for line in path.open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("url") == url:
            return d
    raise SystemExit(f"找不到快照頁面：{url}（{path}）")


FORM_URL = "https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-03-02"

# --- 來源定義 -----------------------------------------------------------
SNAP = {
    "S1": ("extracted_texts.jsonl", "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學", "aca_leave_page.txt"),
    "S2": ("extracted_texts.jsonl", "https://aca.nccu.edu.tw/en/form-download", "aca_form_download_en.txt"),
    "S3": ("extracted_supplementary.jsonl", FORM_URL, "moltke_form_QP-T01-03-02.txt"),
}
LIVE = {   # (網址, 檔名)；moltke 的表單連結現場是 302 轉登入頁，沒有內容，所以沒有 L3
    "L1": ("https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學", "aca_leave_page.html"),
    "L2": ("https://aca.nccu.edu.tw/en/form-download", "aca_form_download_en.html"),
}
SNAP_AS_OF = "2026-08（output/ 快照；moltke 表單 2026-08-21 抓取，版本 202512版）"
LIVE_AS_OF = "2026-11-13（現場）"

# 每個 keypoint 的原文依據：(逐字引句, 來源代號)。S* 是快照，L* 是現場。
LINK_ZH = "[休學/保留學籍申請書](" + FORM_URL + ")"
LINK_EN = "Application Form for Leave of Absence or Retainment of Student Status(休學(保留學籍)申請書)](" + FORM_URL + ")"
K1_REFS = [
    (LINK_ZH, "S1"),
    (LINK_EN, "S2"),
    ("表單編號：QP-T01-03-02", "S3"),
    (LINK_ZH, "L1"),
    (LINK_EN, "L2"),
]
K2_REFS = [
    (LINK_ZH, "S1"),
    (LINK_EN, "S2"),
    (LINK_ZH, "L1"),
    (LINK_EN, "L2"),
]


def main():
    # 1. 取來源文字
    snap_texts = {}
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    for key, (fname_jsonl, url, fname) in SNAP.items():
        rec = snapshot_record(fname_jsonl, url)
        snap_texts[key] = rec["text"]
        (SNAP_DIR / fname).write_text(
            f"# 來源：{url}\n# 檔案：output/aca/{fname_jsonl}\n# 資料日期：{SNAP_AS_OF}\n"
            f"# 以下為該筆記錄的 text 欄位全文（逐字複本）\n\n{rec['text']}\n",
            encoding="utf-8",
        )
    live_texts = {k: html_to_text((LIVE_DIR / f).read_text(encoding="utf-8", errors="ignore")) for k, (_, f) in LIVE.items()}
    src_text = {**snap_texts, **live_texts}
    src_url = {**{k: v[1] for k, v in SNAP.items()}, **{k: v[0] for k, v in LIVE.items()}}

    # 2. 驗證所有引句都逐字在來源裡（空白正規化）；任何一條找不到就中止，不寫檔
    def check(text, src, what):
        if norm(text) not in norm(src_text[src]):
            raise SystemExit(f"找不到原文，中止：[{what}] {text!r} 不在 {src}（{src_url[src]}）")

    all_refs = {"K1": K1_REFS, "K2": K2_REFS}
    for kid, refs in all_refs.items():
        for text, src in refs:
            check(text, src, f"{kid}.references")

    def ref(text, src):
        live = src.startswith("L")
        return {
            "text": text,
            "source_url": src_url[src],
            "source_kind": "live" if live else "snapshot",
            "as_of": LIVE_AS_OF if live else SNAP_AS_OF,
        }

    def refs(kid):
        return [ref(t, s) for t, s in all_refs[kid]]

    gold = {
        "query_id": "leave_form_download",
        "query": "休學申請表在哪裡下載",
        "query_variants": [],
        "query_type": "resource",
        "data_as_of": {
            "snapshot": SNAP_AS_OF,
            "live": LIVE_AS_OF + "；兩個教務處頁面現場仍列有同一個連結；moltke 的表單連結本身現場回 302 轉到同一主機的登入頁，"
                    "沒有跟隨，不知道登入後的內容",
        },
        "content": "休學申請書的名稱是「休學/保留學籍申請書」，表單編號 QP-T01-03-02，下載連結：" + FORM_URL,
        "keypoints": [
            {
                "id": "K1",
                "text": "休學申請書的表單編號是 QP-T01-03-02",
                "required": True,
                "kind": "hard",
                "references": refs("K1"),
                "acceptable_expressions": ["QP-T01-03-02"],
            },
            {
                "id": "K2",
                "text": "休學申請書的下載連結是 " + FORM_URL,
                "required": True,
                "kind": "hard",
                "references": refs("K2"),
                # 用完整網址，不用只寫主機名：moltke.nccu.edu.tw 也會命中其他表單（退學、提早復學）的連結
                "acceptable_expressions": ["moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-03-02"],
            },
        ],
        "source_conflicts": "無。",
        "notes": [
            "K1 的可接受寫法 QP-T01-03-02 也包含在 K2 的網址裡，所以只給連結的答案會同時命中 K1 與 K2（連結裡就有表單編號）。",
            "不列「表單名稱」keypoint：題目已經說「休學申請表」，表單編號足以確認是同一份表（使用者決定）。",
            "不列「答案要簡短、不附完整辦理流程」：那是答案的風格，不是從原文抽取的事實。答案多講的內容由主張層處理："
            "有依據的多講只會拉低「答案為單位 P」（聚焦度的參考），沒有依據的才是幻覺，看有依據比例。資源類題目的報告要把 P 放在 Completeness 旁邊"
            "（使用者決定 2026-11-12，選項 A：多講但有依據算中性）。",
            "K2 要給 moltke 的連結才算；只給教務處頁面（索引）的連結算沒提到，Keypoint 判斷判 irrelevant，不是 wrong。"
            "2026-09-20 那次 Gemma 答案（docs/evidence/2026-09-20_resource_query_run.md）給的就是教務處頁面連結，舊 criteria 判不算。",
            "現場查證：moltke 的表單連結回 302，Location 是同一主機的登入頁 login.formservice?viewdetail=QP-T01-03-02"
            "（formservice_SSO 是單一登入的表單服務）。沒有跟隨，所以不知道登入後會看到什麼、是不是需要校內帳號才能下載。"
            "gold 的標準答案是教務處頁面列出的連結，系統回答時也只能引用這個連結。記錄見 sources/live/live_check.md。",
            "表單本身（moltke 上的 PDF，快照）首行「表單編號：QP-T01-03-02」，標題「國立政治大學 學生□休學□保留學籍 申請書」，版本 202512版；"
            "索引記錄寫承辦單位是教務處註冊組、用途是「休學、保留學籍（服役、懷孕、分娩、撫育三歲以下子女者）申請用」。",
            "語料裡還有很多重複的頁面（中英文、`?start=48` 分頁、各種樣板頁），只列三個正規來源。",
        ],
    }
    out = HERE / "gold.json"
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已寫入 {out.relative_to(ROOT)}")
    print(f"快照原文複本：{len(SNAP)} 份（{SNAP_DIR.relative_to(ROOT)}）")
    print("驗證通過：" + "、".join(f"{k} {len(v)} 條" for k, v in all_refs.items()))


if __name__ == "__main__":
    sys.exit(main())
