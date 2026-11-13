"""
evaluation/dorm_deposit/build_gold.py

建「搬離宿舍如何辦理退還住宿保證金」的 gold（鏈式依賴：填表 → 宿舍服務台檢查寢室簽章 → 三天內持表到住宿組 → 住宿組造冊匯款；順序本身是要考的內容）。

原則（沿用 evaluation/README.md）：抽取，不是生成。每個 reference 的 text 必須逐字出現在來源原文裡（NFKC 正規化、忽略空白與表格線）；
寫檔前逐條驗證，任何一條找不到就中止，不寫檔。表單連結、住宿組與出納組的聯絡人與樓層用 "registry" 欄位引用 evaluation/registry/registry.json。

來源（優先順序：表單 > 住宿組頁面 > 學務處 FAQ > 註冊通知單；衝突時高的是金標準，低的列為可替代並標出來源）：
  S1  住宿輔導組「退離宿程序」頁面（快照，output/osa/extracted_texts.jsonl）
  S2  學務處 FAQ（快照，同上）
  S3  住宿生離宿暨退還「住宿保證金」申請表 QP-M03-01-05（快照，output/osa/extracted_supplementary.jsonl）
  S4  學務處「休（退）學退費標準」頁面（快照；只用來源的住宿組分機那一句）
  S5  休學／保留學籍申請書 QP-T01-03-02（快照，output/aca/extracted_supplementary.jsonl；只用「7 日內退離宿」那一句）
  L1  「退離宿程序」頁面的現場（2026-11-13，curl；連結寫成 [文字](網址)）
  L2  學務處 FAQ 的現場（2026-11-13，curl）
  L3  註冊通知單 115-1（現場靜態抓取的 PDF 轉成文字；只用「未依規定辦理退離宿手續者保證金不予退還」那一句）
不收：學期前退宿（QP-M03-01-04，取消下學期住宿；另一個流程）。

用法（專案根目錄，不上網）：
  python evaluation/dorm_deposit/build_gold.py
輸出：evaluation/dorm_deposit/gold.json、sources/snapshot/*.txt
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

PAGE_URL = "https://osa.nccu.edu.tw/tw/住宿輔導組/宿舍申請與床位資訊/退離宿程序"
FAQ_URL = "https://osa.nccu.edu.tw/tw/faq"
MOLTKE = "https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail="
FORM_URL = MOLTKE + "QP-M03-01-05"
REFUND_URL = "https://osa.nccu.edu.tw/tw/生活事務暨僑生輔導組/學生生活事務/休退學暨研究生畢業退費/休-退-學退費標準"
LEAVE_FORM_URL = MOLTKE + "QP-T01-03-02"
NOTICE_URL = "https://aca.nccu.edu.tw/db/upload/115-1註冊通知單_中文版.pdf"

SNAP_AS_OF = "2026-08（output/ 快照）"
FORM_AS_OF = "2026-08（output/ 快照；表單 QP-M03-01-05）"
LIVE_AS_OF = "2026-11-13（現場）"

SNAP = {   # 代號: (資料夾, jsonl 檔, 網址, 複本檔名, as_of)
    "S1": ("osa", "extracted_texts.jsonl", PAGE_URL, "osa_exit_procedure.txt", SNAP_AS_OF),
    "S2": ("osa", "extracted_texts.jsonl", FAQ_URL, "osa_faq.txt", SNAP_AS_OF),
    "S3": ("osa", "extracted_supplementary.jsonl", FORM_URL, "moltke_form_QP-M03-01-05.txt", FORM_AS_OF),
    "S4": ("osa", "extracted_texts.jsonl", REFUND_URL, "osa_refund_standard.txt", SNAP_AS_OF),
    "S5": ("aca", "extracted_supplementary.jsonl", LEAVE_FORM_URL, "moltke_form_QP-T01-03-02.txt", "2026-08（output/ 快照；表單 QP-T01-03-02，202512版）"),
}
LIVE = {   # 代號: (網址, 檔名, as_of, 是不是 html)
    "L1": (PAGE_URL, "osa_exit_procedure.html", LIVE_AS_OF, True),
    "L2": (FAQ_URL, "osa_faq.html", LIVE_AS_OF, True),
    "L3": (NOTICE_URL, "aca_notice_115_1.pdf.txt", LIVE_AS_OF, False),
}


def norm(s: str) -> str:
    return re.sub(r"[\s|]+", "", unicodedata.normalize("NFKC", s or ""))


def snapshot_record(folder: str, fname: str, url: str) -> dict:
    for line in (ROOT / "output" / folder / fname).open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("url") == url:
            return d
    raise SystemExit(f"找不到快照頁面：{url}（{folder}/{fname}）")


LINK = f"[請下載填寫： 『退離宿暨退還「住宿保證金」申請表』]({FORM_URL})"
RECEIPT = "僅退住宿保證金者可不交宿費收據"
BANK = "由住宿組造冊匯入同學(於政大網頁-在校學生-個人基本資料)登記之帳戶"
NOCLAIM = "若未依退離宿程序辦理退離宿手續者，保證金不予退還"

REFS = {
    "K1": [("填寫列印『離宿暨退還「住宿保證金」申請表』", "S1"), ("填寫列印『離宿暨退還「住宿保證金」申請表』", "L1")],
    "K2": [("宿舍區管理人員檢查寢室", "S3"), ("持上表 至宿舍服務台(檢查寢室簽章)", "S1"), ("持上表 至宿舍服務台(檢查寢室簽章)", "L1")],
    "K3": [("離宿流程：宿舍區管理人員檢查寢室➔三天內至住宿組辦理退費(持本表及宿費收據)", "S3"),
           ("持上表 至宿舍服務台(檢查寢室簽章) ↓ 三天內持上表及「宿費繳費收據」至住宿組(行政大樓3樓)", "S1"),
           ("持上表 至宿舍服務台(檢查寢室簽章) ↓ 三天內持上表及「宿費繳費收據」至住宿組(行政大樓3樓)", "L1")],
    "K4": [("三天內至住宿組辦理退費(持本表及宿費收據)", "S3"), ("三天內持上表及「宿費繳費收據」至住宿組(行政大樓3樓)", "S1"),
           ("三天內持上表及「宿費繳費收據」至住宿組(行政大樓3樓)", "L1")],
    "K5": [("辦理退宿註記、退宿費或住宿保證金", "S1"), ("辦理退宿註記、退宿費或住宿保證金", "L1")],
    "K6": [(BANK, "S3"), (BANK, "S1"), (BANK, "L1")],
    "K7": [(RECEIPT, "S3"), (RECEIPT, "S1"), (RECEIPT, "L1")],
    "K8": [("「宿費繳費收據」若遺失，可請出納組補發", "S3"), ("「宿費繳費收據」若遺失，可至iNccu補發", "S1"), ("「宿費繳費收據」若遺失，可至iNccu補發", "L1")],
    "K9": [("期末規定離宿日前一週內離宿者，本表可交由「宿舍區服務中心/服務台」轉交", "S1"), ("期末規定離宿日前一週內離宿者，本表可交由「宿舍區服務中心/服務台」轉交", "L1")],
    "K10": [("畢業、休學、退學或轉學住宿生應於發生日起7日(含例假日，且不得超過當學期期末所訂離宿日)內向宿舍服務台辦理退離宿手續", "S2"),
            ("畢業、休學、退學或轉學住宿生應於發生日起7日(含例假日，且不得超過當學期期末所訂離宿日)內向宿舍服務台辦理退離宿手續", "L2"),
            ("畢業、休學、退學或轉學住宿生應於發生 日起7日內(含例假日、且不得超過當學期期 末所定離舍日)向住宿組辦理退離宿手續 後，始得申請退還宿費及住宿保證金", "S5")],
    "K11": [(NOCLAIM, "S2"), (NOCLAIM, "L2"), ("若未依規定辦理退離宿手續者，住宿保證金不予退還", "L3")],
    "K12": [("每位住宿生需繳納「住宿保證金」1,000元", "S2"), ("每位住宿生需繳納「住宿保證金」1,000元", "L2"), ("扣款金額若超過住宿保證金1000元以上", "S3")],
    "K13": [("1、財產損失 Property Damage", "S3"), ("2、垃圾清理 Removal of", "S3"), ("3、延遲搬 Extension of dorm stay", "S3")],
    "K14": [("扣款金額若超過住宿保證金1000元以上，另", "S3"), ("予追繳。If the amount of subtractions", "S3")],   # 表單把這句拆在表格的兩列
    "K15": [("僑生及外籍生因離宿後即出國、帳戶已結清無法領取者，另再填", "S3"), ("僑生及外籍生因離宿後即出國、帳戶已結清無法領取者，另再填", "S1"),
            ("僑生及外籍生因離宿後即出國、帳戶已結清無法領取者，另再填", "L1")],
    "K16": [("外籍交換生請向相關系所辦理退還「住宿保證金」", "S3"), ("外籍交換生請向相關系所辦理退還「住宿保證金」", "S1"), ("外籍交換生請向相關系所辦理退還「住宿保證金」", "L1")],
    "K17": [("宿舍相關退費問題，大學部請洽分機62222，研究所請洽分機63251", "S4")],
    "K18": [("表單編號：QP-M03-01-05", "S3"), (LINK, "S1"), (LINK, "L1")],
}


def main() -> int:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    texts, urls, as_of = {}, {}, {}
    for key, (folder, fname, url, out, ao) in SNAP.items():
        rec = snapshot_record(folder, fname, url)
        texts[key], urls[key], as_of[key] = rec["text"], url, ao
        (SNAP_DIR / out).write_text(
            f"# 來源：{url}\n# 檔案：output/{folder}/{fname}\n# 資料日期：{ao}\n# 以下為該筆記錄的 text 欄位全文（逐字複本）\n\n{rec['text']}\n", encoding="utf-8")
    if not (LIVE_DIR / "aca_notice_115_1.pdf.txt").exists():       # 註冊通知單 115-1 的文字（第 4 題抓的，與登記表用同一份）
        shutil.copy(ROOT / "evaluation" / "registry" / "sources" / "live" / "aca_notice_115_1.pdf.txt", LIVE_DIR / "aca_notice_115_1.pdf.txt")
    for key, (url, fname, ao, is_html) in LIVE.items():
        raw = (LIVE_DIR / fname).read_text(encoding="utf-8", errors="ignore")
        texts[key], urls[key], as_of[key] = (html_to_text(raw) if is_html else raw), url, ao

    for kid, refs in REFS.items():
        for text, src in refs:
            if norm(text) not in norm(texts[src]):
                raise SystemExit(f"找不到原文，中止：[{kid}] {text!r} 不在 {src}（{urls[src]}）")

    def refs(kid):
        return [{"text": t, "source_url": urls[s], "source_kind": "live" if s.startswith("L") else "snapshot", "as_of": as_of[s]} for t, s in REFS[kid]]

    def semantic(kid, text, required=True, **extra):
        return {"id": kid, "text": text, "required": required, "kind": "semantic", "references": refs(kid), "acceptable_expressions": [], **extra}

    def registry(kid, text, reg, value_check, required=True, **extra):
        return {"id": kid, "text": text, "required": required, "kind": "hard", "value_check": value_check, "registry": reg, **extra}

    keypoints = [
        semantic("K1", "要先填寫列印「離宿暨退還住宿保證金申請表」"),
        semantic("K2", "要持表到宿舍服務台，請宿舍管理人員檢查寢室並簽章"),
        semantic("K3", "順序：要先經宿舍服務台檢查寢室簽章，之後才到住宿組辦理"),
        semantic("K4", "檢查寢室後三天內，要持表及宿費繳費收據到住宿組辦理"),
        semantic("K5", "住宿組辦理退宿註記、退宿費或住宿保證金"),
        semantic("K6", "退款由住宿組造冊，匯入學生在個人基本資料登記的帳戶"),
        semantic("K7", "只退住宿保證金的人，可以不交宿費繳費收據"),
        semantic("K8", "宿費繳費收據遺失可以補發（可到 iNccu 補發或請出納組補發）", required=False),
        semantic("K9", "期末規定離宿日前一週內離宿者，申請表可交由宿舍區服務中心／服務台轉交", required=False),
        semantic("K10", "畢業、休學、退學或轉學的住宿生，要在發生日起 7 日內（含例假日，且不得超過當學期期末所訂離宿日）辦理退離宿手續"),
        semantic("K11", "沒有依退離宿程序辦理退離宿手續的人，住宿保證金不予退還"),
        {"id": "K12", "text": "住宿保證金是 1,000 元", "required": True, "kind": "hard", "references": refs("K12"),
         "acceptable_expressions": ["1,000", "1000", "一千"]},
        semantic("K13", "保證金扣款的項目有財產損失、垃圾清理、延遲搬離等", required=False),
        semantic("K14", "扣款金額超過住宿保證金 1,000 元的部分，另行追繳", required=False),
        semantic("K15", "僑生及外籍生離宿後即出國、帳戶已結清無法領取者，要另外填代領人帳戶領據，到相關系所辦理",
                 applies_if="答案提到僑生或外籍生"),
        semantic("K16", "外籍交換生要向相關系所辦理退還住宿保證金", applies_if="答案提到外籍交換生"),
        semantic("K17", "宿舍相關退費問題，大學部洽分機 62222，研究所洽分機 63251", required=False),
        {"id": "K18", "text": "申請書是「離宿暨退還住宿保證金申請表」，表單編號 QP-M03-01-05", "required": True, "kind": "hard",
         "references": refs("K18"), "acceptable_expressions": ["QP-M03-01-05"]},
        registry("K19", "離宿暨退還住宿保證金申請表的下載連結是 " + FORM_URL, {"need": "form_link", "form": "QP-M03-01-05", "mention": "always"}, "registry_form_link"),
        registry("K20", "住宿組在行政大樓三樓", {"office": "dorm", "need": "floor"}, "registry_floor"),
        registry("K21", "答案要寫出住宿組的聯絡人：住宿組任何一位的姓名或職稱加分機", {"office": "dorm", "need": "who"}, "registry_who"),
        registry("K22", "答案提到出納組時，要寫出出納組任何一位的姓名或職稱加分機，或出納組的代表線",
                 {"office": "cashier", "need": "who", "conditional": True}, "registry_who", required=False, applies_if="答案提到出納組"),
        registry("K23", "答案提到出納組時，要寫出出納組的樓層", {"office": "cashier", "need": "floor", "conditional": True}, "registry_floor",
                 required=False, applies_if="答案提到出納組"),
    ]
    gold = {
        "query_id": "dorm_deposit",
        "query": "搬離宿舍如何辦理退還住宿保證金",
        "query_variants": [],
        "query_type": "procedure",
        "data_as_of": {
            "snapshot": SNAP_AS_OF + "；表單 " + FORM_AS_OF,
            "live": LIVE_AS_OF + "（住宿組「退離宿程序」頁、學務處 FAQ，curl；moltke 表單連結回 302 轉登入頁，沒有跟隨）；住宿組、出納組的聯絡人與樓層的現場依據在 evaluation/registry/",
        },
        "content": (
            "搬離宿舍要退還住宿保證金，順序是：先填寫列印「離宿暨退還住宿保證金申請表」（表單編號 QP-M03-01-05，" + FORM_URL + "），"
            "持表到宿舍服務台請管理人員檢查寢室並簽章，再在三天內持表及宿費繳費收據到住宿組（行政大樓三樓）辦理退宿註記、退宿費或住宿保證金，"
            "由住宿組造冊匯入學生在個人基本資料登記的帳戶。只退住宿保證金者可以不交宿費繳費收據；畢業、休學、退學或轉學的住宿生要在發生日起 7 日內辦理；"
            "沒有依程序辦理退離宿的人，住宿保證金（1,000 元）不予退還。"
        ),
        "keypoints": keypoints,
        "source_conflicts": (
            "來源優先順序：表單 > 住宿組頁面 > 學務處 FAQ > 註冊通知單；高的是金標準，低的列為可替代。"
            "（1）宿費繳費收據遺失：頁面寫「可至 iNccu 補發（補印）」，表單寫「可請出納組補發」；兩種都算對（K8）。"
            "（2）畢業、休學、退學、轉學的 7 日內退離宿：FAQ 寫向「宿舍服務台」辦理，休學申請書（QP-T01-03-02）寫向「住宿組」辦理；K10 只收「7 日內辦理退離宿手續」，不指定去哪個單位，兩種寫法都不判錯。"
            "（3）學期末的流程：頁面只寫到宿舍服務台簽章，表單的通則是檢查寢室後三天內至住宿組；K9 只收頁面明寫的轉交規則。"
            "（4）僑外生的代領人表單名稱：頁面寫「申請退還『住宿保證金』匯入代理人申請表」，表單寫「僑外生退住宿保證金轉入代領人帳戶領據」；K15 只收「另外填代領人帳戶領據」這件事，不指定表單名稱。"
        ),
        "notes": [
            "鏈式依賴：順序是這題要考的內容，所以用專門的 K3（先檢查寢室簽章、之後才到住宿組）考順序，不依賴主張的切法保留順序（議題 F2：切細會丟順序）；K4（三天內）是時限。",
            "住宿組的聯絡人與樓層引用登記表（K20、K21，必要）；出納組只在答案提到時才適用（K22、K23，選擇性、條件式）。",
            "選擇性：K8、K9、K13、K14、K17、K22、K23；條件式：K15（提到僑生或外籍生）、K16（提到外籍交換生）、K22、K23。「必要」目前不影響評分（議題 F8、F9）。",
            "K10（7 日內）列為必要：它回答「什麼時候要搬」；K12（1,000 元）用 hard（數字），寫成「1,000」「1000」「一千」都算。",
            "不收：學期前退宿（QP-M03-01-04，取消／放棄下學期住宿，另一個流程，不是搬離宿舍；使用者決定 2026-11-13）、暑宿費退費、宿費退費比例（2/3、1/2、不退）。",
            "moltke 的表單連結現場回 302 轉登入頁（2026-11-13，curl，沒有跟隨），連結本身有效、看不到表單內容；表單內容以快照為準。記錄見 sources/live/live_check.md 與登記表。",
        ],
    }
    out = HERE / "gold.json"
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已寫入 {out.relative_to(ROOT)}（{len(keypoints)} 個 keypoint，其中 {sum(1 for k in keypoints if k.get('registry'))} 個引用登記表）")
    print(f"引句驗證通過：{len(REFS)} 個 keypoint，{sum(len(v) for v in REFS.values())} 條")
    return 0


if __name__ == "__main__":
    sys.exit(main())
