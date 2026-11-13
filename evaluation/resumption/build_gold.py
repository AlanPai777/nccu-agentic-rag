"""
evaluation/resumption/build_gold.py

建「如何辦理復學」的 gold（程序類、跨處室；phase_k_evaluation_design.md 第 5 節的格式）。

原則（沿用 evaluation/README.md）：抽取，不是生成。gold 裡每個 reference 的 text 必須逐字出現在來源原文裡
（NFKC 正規化、忽略空白與表格線）；寫檔前逐條驗證，任何一條找不到就中止，不寫檔。

人員、分機、樓層、表單連結不在這裡存引句：這些 keypoint 用 "registry" 欄位引用 evaluation/registry/registry.json
（各題共用、只維護一份，引句由登記表自己驗證）。這裡只存這一題才成立的事實。

來源（優先順序：表單 > 註冊通知單 115-1 > 教務處頁面 > 學則；衝突時高的是金標準，低的列為可替代並標出來源）：
  S1  教務處「休學、保留學籍、退學、提早復學」頁面（快照，output/aca/extracted_texts.jsonl）
  S2  學則 law01A.pdf（快照，同上）
  S3  提早復學申請書 QP-T01-03-04（快照，output/aca/extracted_supplementary.jsonl，2024修訂8版）
  L1  同一個教務處頁面的現場（2026-11-13，連結寫成 [文字](網址)）
  L4  註冊通知單 115-1（現場靜態抓取的 PDF，轉成文字）

用法（專案根目錄，不上網）：
  python evaluation/resumption/build_gold.py
輸出：evaluation/resumption/gold.json、sources/snapshot/*.txt
"""
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "evaluation"))
from gold_check import html_to_text  # noqa: E402

LIVE_DIR = HERE / "sources" / "live"
SNAP_DIR = HERE / "sources" / "snapshot"
REG_LIVE = ROOT / "evaluation" / "registry" / "sources" / "live"

PAGE_URL = "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學"
LAW_URL = "https://aca.nccu.edu.tw/download/rulesdata/law01A.pdf"
FORM_URL = "https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-03-04"
NOTICE_URL = "https://aca.nccu.edu.tw/db/upload/115-1註冊通知單_中文版.pdf"

SNAP_AS_OF = "2026-08（output/ 快照）"
FORM_AS_OF = "2026-08（output/ 快照；表單版本 2024修訂8版）"
LIVE_AS_OF = "2026-11-13（現場）"

SNAP = {   # 代號: (jsonl 檔, 網址, 複本檔名, as_of)
    "S1": ("extracted_texts.jsonl", PAGE_URL, "aca_leave_page.txt", SNAP_AS_OF),
    "S2": ("extracted_texts.jsonl", LAW_URL, "aca_rules_law01A.txt", SNAP_AS_OF),
    "S3": ("extracted_supplementary.jsonl", FORM_URL, "moltke_form_QP-T01-03-04.txt", FORM_AS_OF),
}
LIVE = {   # 代號: (網址, 檔名, as_of, 是不是 html)
    "L1": (PAGE_URL, "aca_leave_page.html", LIVE_AS_OF, True),
    "L4": (NOTICE_URL, "aca_notice_115_1.pdf.txt", LIVE_AS_OF, False),
}


def norm(s: str) -> str:
    return re.sub(r"[\s|]+", "", unicodedata.normalize("NFKC", s or ""))


def snapshot_record(fname: str, url: str) -> dict:
    for line in (ROOT / "output" / "aca" / fname).open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("url") == url:
            return d
    raise SystemExit(f"找不到快照頁面：{url}（{fname}）")


# --- 每個 keypoint 的原文依據：(逐字引句, 來源代號)，優先順序高的在前 ------------------
LINK = lambda text, fid: f"[{text}](https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail={fid})"  # noqa: E731
Q_EARLY = "二、如於尚未期滿前擬辦提早復學，應於復學之當學期加退選結束前，本人攜帶學生證或身分證件正本"
Q_POA = "（非本人親辦，需附委託書及被委託人身分證件正本），填妥「提早復學申請書」"
Q_CHAIN = "註 冊 組 承 辦 人 | 擬 准予 學年第 學期復學。 學士班請加會學士班統籌； |  |  | 註 冊 組 組 長"

REFS = {
    "K1": [("一、學生休學或保留學籍期滿即應復學，並依規定期限辦妥繳費註冊相關事宜", "S1"),
           ("一、學生休學或保留學籍期滿即應復學，並依規定期限辦妥繳費註冊相關事宜", "L1")],
    "K2": [("二、 提前復學之申請，請於欲復學之當學期加退選結束前（學則第43條）書面提出申請", "S3"),
           ("應於復學之當學期加退選結束前辦理完成復學程序", "S2"),
           ("二、如於尚未期滿前擬辦提早復學，應於復學之當學期加退選結束前", "S1"),
           ("二、如於尚未期滿前擬辦提早復學，應於復學之當學期加退選結束前", "L1")],
    "K3": [("表單編號：QP-T01-03-04", "S3"), (LINK("提早復學申請書", "QP-T01-03-04"), "S1"), (LINK("提早復學申請書", "QP-T01-03-04"), "L1")],
    "K5": [(Q_EARLY, "S1"), (Q_EARLY, "L1")],
    "K6": [(Q_POA, "S1"), (Q_POA, "L1")],
    "K8": [("系 所 會 辦", "S3"), ("依說明至系所及各處室蓋章後，送至教務處註冊組", "S1")],
    "K9": [("生 僑 組 | (僅男生及僑生需辦理)", "S3")],
    "K10": [("(請繳交歸屬證書正本或體位證書正本或退伍令影本)", "S3")],
    "K11": [("國 際 合 作 事 務 處 | （僅國際學生需辦理）", "S3")],
    "K12": [(Q_CHAIN, "S3")],
    "K13": [("學士班請加會學士班統籌", "S3")],
    "K14": [("請至各單位（雙線以上）蓋章完畢後，送註冊組辦理", "S3"),
            ("依說明至系所及各處室蓋章後，送至教務處註冊組", "S1")],
    "K21": [("完成復學手續後，應依規定期限辦理註冊", "S3"),
            ("並依規定期限辦妥註冊相關事宜", "S1")],
    "K22": [("限於第一學期申請（每年 八月），第二學期不得申請入學", "S3")],
    "K23": [("本申請經核准後，即完成復學手續", "S3")],
    "K24": [("依規定完成繳費註冊、選課上課者，即完成復學手續", "L4")],
}


def main() -> int:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    texts, urls, as_of = {}, {}, {}
    for key, (fname, url, out, ao) in SNAP.items():
        rec = snapshot_record(fname, url)
        texts[key], urls[key], as_of[key] = rec["text"], url, ao
        (SNAP_DIR / out).write_text(
            f"# 來源：{url}\n# 檔案：output/aca/{fname}\n# 資料日期：{ao}\n# 以下為該筆記錄的 text 欄位全文（逐字複本）\n\n{rec['text']}\n",
            encoding="utf-8")
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    if not (LIVE_DIR / "aca_leave_page.html").exists():     # 現場教務處頁面（2026-11-13）：與登記表用同一份，不重抓
        shutil.copy(REG_LIVE / "aca_leave_page.html", LIVE_DIR / "aca_leave_page.html")
    for key, (url, fname, ao, is_html) in LIVE.items():
        raw = (LIVE_DIR / fname).read_text(encoding="utf-8", errors="ignore")
        texts[key], urls[key], as_of[key] = (html_to_text(raw) if is_html else raw), url, ao

    for kid, refs in REFS.items():
        for text, src in refs:
            if norm(text) not in norm(texts[src]):
                raise SystemExit(f"找不到原文，中止：[{kid}] {text!r} 不在 {src}（{urls[src]}）")

    def refs(kid):
        return [{"text": t, "source_url": urls[s], "source_kind": "live" if s.startswith("L") else "snapshot", "as_of": as_of[s]}
                for t, s in REFS[kid]]

    def semantic(kid, text, required=True, **extra):
        return {"id": kid, "text": text, "required": required, "kind": "semantic", "references": refs(kid),
                "acceptable_expressions": [], **extra}

    def registry(kid, text, reg, value_check, required=True, **extra):
        return {"id": kid, "text": text, "required": required, "kind": "hard", "value_check": value_check, "registry": reg, **extra}

    keypoints = [
        semantic("K1", "休學或保留學籍期滿即應復學，並要依規定期限辦妥繳費註冊"),
        semantic("K2", "提早復學要在復學當學期的加退選結束前辦理"),
        {"id": "K3", "text": "提早復學的表單是「提早復學申請書」，表單編號 QP-T01-03-04", "required": True, "kind": "hard",
         "references": refs("K3"), "acceptable_expressions": ["QP-T01-03-04"]},
        registry("K4", "提早復學申請書的下載連結是 " + FORM_URL, {"need": "form_link", "form": "QP-T01-03-04", "mention": "always"}, "registry_form_link"),
        semantic("K5", "辦理提早復學要本人攜帶學生證或身分證件正本"),
        semantic("K6", "非本人親辦，需附委託書及被委託人的身分證件正本", required=False),
        registry("K7", "答案提到委託書時，要附委託書的連結（各項證明文件申辦委託書，QP-T01-02-05）",
                 {"need": "form_link", "form": "QP-T01-02-05", "mention": "conditional"}, "registry_form_link",
                 applies_if="答案提到委託書"),
        semantic("K8", "提早復學申請書要請系所會辦蓋章"),
        semantic("K9", "生僑組蓋章只有男生及僑生需要辦理"),
        semantic("K10", "到生僑組要繳交歸屬證書正本、體位證書正本或退伍令影本（三者擇一）", required=False,
                 applies_if="答案提到生僑組"),
        semantic("K11", "國際合作事務處蓋章只有國際學生需要辦理"),
        semantic("K12", "註冊組先由承辦人擬准復學，再由註冊組組長蓋章"),
        semantic("K13", "學士班的申請另要加會學士班統籌"),
        semantic("K14", "各單位蓋章完畢後，送註冊組辦理"),
        registry("K15", "答案要寫出註冊組的聯絡人：註冊組任何一位的姓名或職稱加分機", {"office": "registrar", "need": "who"}, "registry_who"),
        registry("K16", "註冊組在行政大樓四樓", {"office": "registrar", "need": "floor"}, "registry_floor"),
        registry("K17", "答案提到生僑組時，要寫出生僑組任何一位的姓名或職稱加分機", {"office": "soa", "need": "who", "conditional": True},
                 "registry_who", applies_if="答案提到生僑組"),
        registry("K18", "答案提到生僑組時，要寫出生僑組在行政大樓三樓", {"office": "soa", "need": "floor", "conditional": True},
                 "registry_floor", applies_if="答案提到生僑組"),
        registry("K19", "答案提到國合處時，要寫出國合處任何一位的姓名或職稱加分機，或國合處的代表線",
                 {"office": "oic", "need": "who", "conditional": True}, "registry_who", applies_if="答案提到國合處"),
        registry("K20", "答案提到國合處時，要寫出國際教育組在行政大樓八樓",
                 {"office": "oic", "need": "floor", "unit": "國際教育組", "conditional": True}, "registry_floor",
                 applies_if="答案提到國合處"),
        semantic("K21", "完成復學手續後，要依規定期限辦理註冊"),
        semantic("K22", "原保留入學資格者因原因消失想提早復學，只限第一學期（每年八月）申請，第二學期不得申請"),
        semantic("K23", "提早復學申請經核准後，即完成復學手續", required=False),
        semantic("K24", "期滿者依規定完成繳費註冊、選課上課，即完成復學手續", required=False),
    ]
    gold = {
        "query_id": "resumption",
        "query": "如何辦理復學",
        "query_variants": [],
        "query_type": "procedure",
        "data_as_of": {
            "snapshot": SNAP_AS_OF + "；表單 " + FORM_AS_OF,
            "live": LIVE_AS_OF + "（教務處頁面、註冊通知單 115-1、各處室人員頁；人員、樓層、表單連結的現場依據在 evaluation/registry/）",
        },
        "content": (
            "休學或保留學籍期滿者，依規定完成繳費註冊、選課上課，即完成復學手續。"
            "如要在期滿前提早復學，須在復學當學期加退選結束前，本人攜帶學生證或身分證件正本（非本人親辦需附委託書及被委託人身分證件正本），"
            "填妥「提早復學申請書」（表單編號 QP-T01-03-04，" + FORM_URL + "），"
            "請系所會辦、生僑組（僅男生及僑生，需繳交歸屬證書正本、體位證書正本或退伍令影本）、國際合作事務處（僅國際學生）蓋章，"
            "再由註冊組承辦人擬准、組長蓋章（學士班另加會學士班統籌），蓋章完畢後送註冊組辦理。"
            "申請經核准即完成復學手續，之後依規定期限辦理註冊。原保留入學資格者只限第一學期（每年八月）申請。"
        ),
        "keypoints": keypoints,
        "source_conflicts": (
            "來源優先順序：表單 > 註冊通知單 115-1 > 教務處頁面 > 學則 > 人員頁；高的是金標準。"
            "K1 的「選課上課」只有註冊通知單 115-1 寫，教務處頁面只寫「繳費註冊」；以通知單為準，兩者不衝突（頁面較簡略）。"
            "人員姓名：教務處註冊組的現場頁面現在只顯示姓氏加職稱（如「王組長」），快照索引（2026-08-25）是全名；兩種都算對，見登記表。"
        ),
        "notes": [
            "人員、分機、樓層、表單連結用 registry 欄位引用 evaluation/registry/registry.json，條件式的（生僑組、國合處、委託書）在答案沒提到時不適用、不計入。",
            "蓋章的適用對象拆成一個單位一個 keypoint（K8、K9、K11、K12、K13），符合「一個 keypoint 一個事實」；要合成「蓋章順序」一個重點，把 K8–K14 合併即可。",
            "不收：教務長那一層簽核（由主張層處理）、銜接原學年（原文 S1 第三點，選擇不收）、後備軍人復學生的日期（每學期不同，通知單寫 115年9月11日，不收）。",
            "K10、K23、K24 是選擇性：K10 只適用於男生、僑生的路徑；K23（提早復學核准即完成）與 K24（期滿者繳費註冊、選課上課即完成）只當加分。",
            "K1 與 K24 是同一句話的兩半（議題 F16，使用者決定拆開）：K1 是教務處頁面也有的「期滿即應復學，依規定期限辦妥繳費註冊」（必要）；K24 的「選課上課」只有註冊通知單 115-1 寫，系統不一定會讀，所以選擇性。",
            "moltke 的表單連結現場回 302 轉登入頁（QP-T01-02-05、QP-T01-03-02 已查，見登記表與 sources/live/live_check.md）；QP-T01-03-04 沒有送過現場請求，連結以教務處現場頁面列出的為準。",
        ],
    }
    out = HERE / "gold.json"
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已寫入 {out.relative_to(ROOT)}（{len(keypoints)} 個 keypoint，其中 {sum(1 for k in keypoints if k.get('registry'))} 個引用登記表）")
    print("引句驗證通過：" + "、".join(f"{k} {len(v)} 條" for k, v in REFS.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
