"""
evaluation/course_limit/build_gold.py

建「選課上限幾學分」的 gold（phase_k_evaluation_design.md 第 5 節的格式）。

原則（沿用 evaluation/README.md）：抽取，不是生成。gold 裡每個 reference 的 text
必須逐字出現在來源原文裡；寫檔前逐條驗證（忽略空白，做 Unicode 相容正規化），
任何一條找不到就中止，不寫檔。

來源：
  - snapshot：output/ 的快照（讀 output/aca/extracted_texts.jsonl，不上網）
  - live：sources/live/ 的 2026-11-11 現場頁面（已存檔，本腳本不上網；PDF 用 pdfplumber 轉文字，
    寫成 <檔名>.pdf.txt，供 evaluation/gold_check.py 驗證）

用法（在專案根目錄）：
  python evaluation/course_limit/build_gold.py
輸出：
  evaluation/course_limit/gold.json
  evaluation/course_limit/sources/snapshot/*.txt（引用到的快照原文複本）
  evaluation/course_limit/sources/live/*.pdf.txt（現場 PDF 的文字）
"""
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LIVE_DIR = HERE / "sources" / "live"
SNAP_DIR = HERE / "sources" / "snapshot"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"[\s|]+", "", s)


def live_html_text(name: str) -> str:
    raw = (LIVE_DIR / name).read_text(encoding="utf-8", errors="ignore")
    raw = re.sub(r"(?s)<(script|style).*?</\1>", "", raw)
    raw = re.sub(r"<[^>]+>", "\n", raw)
    return html.unescape(raw)


def live_pdf_text(name: str) -> str:
    with pdfplumber.open(LIVE_DIR / name) as pdf:
        text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    (LIVE_DIR / f"{name}.txt").write_text(text, encoding="utf-8")
    return text


def snapshot_record(subdomain: str, url: str) -> dict:
    path = ROOT / "output" / subdomain / "extracted_texts.jsonl"
    for line in path.open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("url") == url:
            return d
    raise SystemExit(f"找不到快照頁面：{url}（{path}）")


# --- 來源定義 -----------------------------------------------------------
SNAP = {
    "S1": ("aca", "https://aca.nccu.edu.tw/download/rulesdata/law01A.pdf", "aca_law01A.txt"),
    "S2": ("aca", "https://aca.nccu.edu.tw/zh/常用連結/教務處qa/選課業務", "aca_faq_course_selection.txt"),
    "S3": ("aca", "https://aca.nccu.edu.tw/download/course/選課須知11407.pdf", "aca_course_notice_11407.txt"),
    "S4": ("aca", "https://aca.nccu.edu.tw/download/course/選課Q&A_11407.pdf", "aca_course_qa_11407.txt"),
    "S5": ("aca", "https://aca.nccu.edu.tw/download/flowProcess/file/register/register18.pdf", "aca_register18_overload_flow.txt"),
}
# 現場：(網址, 檔名, 類型)。S5（超減修流程）沒有現場請求，只有快照。
LIVE = {
    "L1": ("https://aca.nccu.edu.tw/download/rulesdata/law01A.pdf", "aca_law01A.pdf", "pdf"),
    "L2": ("https://aca.nccu.edu.tw/zh/常用連結/教務處qa/選課業務", "aca_faq_course_selection.html", "html"),
    "L3": ("https://aca.nccu.edu.tw/download/course/選課須知11407.pdf", "aca_course_notice_11407.pdf", "pdf"),
    "L4": ("https://aca.nccu.edu.tw/download/course/選課Q&A_11407.pdf", "aca_course_qa_11407.pdf", "pdf"),
}
SNAP_AS_OF = "2026-08（output/ 快照）"
LIVE_AS_OF = "2026-11-11（現場）"

# 每個 keypoint 的原文依據：(逐字引句, 來源代號)。S* 是快照，L* 是現場。
# 引句只取一個事實的最短原文；同一事實在多份來源的寫法不同，全部列出。
K1_REFS = [
    ("學士班學生第一至第三學年每學期修習學分，不得少於十二學分，不得多於二十五學分", "S1"),
    ("本校學士班學生每學期上限為25學分", "S2"),
    ("無加修學系者為25學分", "S3"),
    ("學士班學生第一至第三學年每學期修習學分，不得少於十二學分，不得多於二十五學分", "L1"),
    ("本校學士班學生每學期上限為25學分", "L2"),
    ("無加修學系者為25學分", "L3"),
]
K2_REFS = [
    ("具雙主修身分者學分修習上限提高為31學分，具輔系身分者學分修習上限提高為28學分", "S3"),
    ("具雙主修身分者為31學分，具輔系身分者為28學分，無加修學系或未申請超修者為25學分", "S4"),
    ("具雙主修身分者學分修習上限提高為31學分，具輔系身分者學分修習上限提高為28學分", "L3"),
    ("具雙主修身分者為31學分，具輔系身分者為28學分，無加修學系或未申請超修者為25學分", "L4"),
]
K3_REFS = [
    ("學生若因情況特殊，經系主任核可者，得於當學期超修或減修學分。超減修至多以六學分為限", "S1"),
    ("學士班學生若因特殊需要得申請超修至多6學分，亦得減修學分至多6學分", "S2"),
    ("學士班學生如因課程規劃及選課需要，預計於本學期修習學分數超過或低於學則規定之學分上下限者，應於規定期限內上網提出「超減修習學分數」申請", "S3"),
    ("學士班學生學期超減修習學分數申請作業流程", "S5"),
    ("超減修至多以六學分為限", "S5"),
    ("學生若因情況特殊，經系主任核可者，得於當學期超修或減修學分。超減修至多以六學分為限", "L1"),
    ("學士班學生若因特殊需要得申請超修至多6學分，亦得減修學分至多6學分", "L2"),
    ("學士班學生如因課程規劃及選課需要，預計於本學期修習學分數超過或低於學則規定之學分上下限者，應於規定期限內上網提出「超減修習學分數」申請", "L3"),
]
K4_REFS = [
    ("碩、博士班學生每學期修習學分由各系(所)自定", "S1"),
    ("碩、博士班學生學分數則從各所修業規定", "S2"),
    ("碩博士班學生依各系所修業規定", "S4"),
    ("碩、博士班學生每學期修習學分由各系(所)自定", "L1"),
    ("碩、博士班學生學分數則從各所修業規定", "L2"),
    ("碩博士班學生依各系所修業規定", "L4"),
]
K5_REFS = [
    ("第一至第三學年每學期修習學分，不得少於十二學分", "S1"),
    ("第四學年每學期不得少於十學分", "S1"),
    ("大一至大三下限為12學分，大四為10學分", "S2"),
    ("學士班學生第一至第三學年每學期修習學分，不得少於12學分，第四學年每學期不得少於10學分", "S3"),
    ("第一至第三學年每學期修習學分，不得少於十二學分", "L1"),
    ("第四學年每學期不得少於十學分", "L1"),
    ("大一至大三下限為12學分，大四為10學分", "L2"),
    ("學士班學生第一至第三學年每學期修習學分，不得少於12學分，第四學年每學期不得少於10學分", "L3"),
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
    live_texts = {}
    for key, (_, fname, kind) in LIVE.items():
        live_texts[key] = live_pdf_text(fname) if kind == "pdf" else live_html_text(fname)
    src_text = {**snap_texts, **live_texts}
    src_url = {**{k: v[1] for k, v in SNAP.items()}, **{k: v[0] for k, v in LIVE.items()}}

    # 2. 驗證所有引句都逐字在來源裡（空白正規化）；任何一條找不到就中止，不寫檔
    def check(text, src, what):
        if norm(text) not in norm(src_text[src]):
            raise SystemExit(f"找不到原文，中止：[{what}] {text!r} 不在 {src}（{src_url[src]}）")

    all_refs = {"K1": K1_REFS, "K2": K2_REFS, "K3": K3_REFS, "K4": K4_REFS, "K5": K5_REFS}
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
        "query_id": "course_limit",
        "query": "選課上限幾學分",
        "query_variants": [],
        "query_type": "knowledge",
        "data_as_of": {
            "snapshot": SNAP_AS_OF,
            "live": LIVE_AS_OF + "；學則、教務處 QA、選課須知（114.07）、選課 Q&A（114.07）四份與快照逐字一致；"
                    "超減修申請流程（register18.pdf）只有快照，沒有現場請求",
        },
        "content": (
            "學士班學生每學期選課學分上限為 25 學分（第一至第三學年每學期不得少於 12 學分，第四學年不得少於 10 學分）。"
            "具雙主修身分者上限提高為 31 學分，具輔系身分者為 28 學分。"
            "經系主任核可，學士班學生可超修或減修學分，至多 6 學分。"
            "碩、博士班每學期修習學分由各系（所）自定。"
        ),
        "keypoints": [
            {
                "id": "K1",
                "text": "學士班學生每學期修習學分上限為 25 學分",
                "required": True,
                "kind": "hard",
                "references": refs("K1"),
                "acceptable_expressions": ["25學分", "25 學分", "二十五學分"],
            },
            {
                "id": "K2",
                "text": "具雙主修身分者每學期學分上限提高為 31 學分，具輔系身分者提高為 28 學分（無加修學系者為 25 學分）",
                "required": True,
                # 要同時講到 31 與 28 兩個數字；規則版是「命中任一個表達式就算 hit」，會讓只講一個的答案誤判為 hit，
                # 所以設成 semantic，交給階段 3 的 Keypoint 判斷（見 notes）
                "kind": "semantic",
                "references": refs("K2"),
                "acceptable_expressions": ["31學分", "31 學分", "三十一學分", "28學分", "28 學分", "二十八學分"],
            },
            {
                "id": "K3",
                "text": "經系主任核可，學士班學生可於當學期超修或減修學分，超減修至多 6 學分",
                "required": True,
                # 條件加數字兩件事，同樣設成 semantic
                "kind": "semantic",
                "references": refs("K3"),
                "acceptable_expressions": ["超修", "減修", "超減修", "6學分", "六學分"],
            },
            {
                "id": "K4",
                "text": "碩、博士班學生每學期修習學分由各系（所）自定，沒有全校統一的上限",
                "required": True,
                "kind": "hard",
                "references": refs("K4"),
                "acceptable_expressions": ["各系(所)自定", "各系（所）自定", "各系所自定", "由各系所", "各所修業規定",
                                           "各系所修業規定", "依各系所", "各系所規定", "各系所的規定"],
            },
            {
                "id": "K5",
                "text": "學士班學生每學期修習學分的下限：第一至第三學年 12 學分，第四學年 10 學分",
                "required": True,
                # 要同時講到 12 與 10；同樣設成 semantic
                "kind": "semantic",
                "references": refs("K5"),
                "acceptable_expressions": ["12學分", "12 學分", "十二學分", "10學分", "10 學分", "十學分"],
            },
        ],
        "source_conflicts": (
            "無矛盾。有一處來源沒有解釋：學則與 FAQ 說超減修「至多 6 學分」（25＋6＝31），"
            "選課須知與選課 Q&A 說輔系上限是 28、雙主修是 31；輔系的 28 與超減修至多 6 的關係，來源沒有說明。"
            "兩者各自照來源記錄，不自行推論。"
        ),
        "notes": [
            "「超修後每學期最高 31 學分」沒有列為 keypoint：使用者的說明是超減修不分有無輔系或雙主修皆可申請、最高 31，"
            "但現場查證 7 個頁面與本地快照（學則、FAQ、選課須知、選課 Q&A、超減修流程、選課辦法）都沒有一句明說，"
            "31 只出現在「具雙主修身分者…提高為31學分」。依使用者的決定，沒找到原文就不列入；"
            "若之後找到明文，再補一個 keypoint。",
            "K2、K3、K5 設為 semantic（不是 hard）：它們各要同時講到兩個以上的數值或條件，"
            "規則版 Accuracy 是「命中任一 acceptable_expressions 就算 hit」，只講一半也會被判 hit。"
            "多值型 keypoint 要不要在規則版支援「全部都要出現」（例如 all_of），等更多題目都跑出答案後再設計。",
            "超減修流程（register18.pdf，113.09 修訂）只有快照，沒有現場請求，標 source_kind=snapshot；"
            "它說明超減修是學士班學生通用的申請流程，由學系主任審核。",
            "延畢生：FAQ 寫「延畢生則僅規定至少應修一門課程」，超減修流程寫「延後畢業學生不須減修申請，但每學期需修至少1門課」；"
            "題目問上限，延畢生不列為 keypoint。",
            "碩、博士班各系所有自己的規定（例如快照裡有的系所寫上限 12、14、18 學分不等），gold 只記「由各系所自定」，"
            "不列個別系所，因為題目沒有指定系所。",
            "選課須知與選課 Q&A 現場仍是 11407（114.07）版；教務處首頁的連結也仍指向這個檔案。",
            "查證記錄見 sources/live/live_check.md；沒有 query_variants。",
        ],
    }
    out = HERE / "gold.json"
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已寫入 {out.relative_to(ROOT)}")
    print(f"快照原文複本：{len(SNAP)} 份（{SNAP_DIR.relative_to(ROOT)}）；現場 PDF 文字 {sum(1 for v in LIVE.values() if v[2] == 'pdf')} 份")
    print("驗證通過：" + "、".join(f"{k} {len(v)} 條" for k, v in all_refs.items()))


if __name__ == "__main__":
    sys.exit(main())
