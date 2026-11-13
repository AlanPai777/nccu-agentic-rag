"""
evaluation/leave_of_absence/build_gold.py

建「如何辦理休學」的 gold（程序類、跨處室；phase_k_evaluation_design.md 第 5 節的格式）。
舊的事實表在 evaluation/old_leave_of_absence/，只當參考；這裡的來源是從 output/ 與現場頁面重新抽取的。

原則（沿用 evaluation/README.md）：抽取，不是生成。每個 reference 的 text 必須逐字出現在來源原文裡
（NFKC 正規化、忽略空白與表格線）；寫檔前逐條驗證，任何一條找不到就中止，不寫檔。
人員、分機、樓層、表單連結不在這裡存引句：這些 keypoint 用 "registry" 欄位引用 evaluation/registry/registry.json。

來源（優先順序：表單 > 學務處退費標準頁 > 教務處頁面 > 學則；衝突時高的是金標準，低的列為可替代並標出來源）：
  S1  教務處「休學、保留學籍、退學、提早復學」頁面（快照）
  S2  學則 law01A.pdf（快照）
  S3  休學／保留學籍申請書 QP-T01-03-02（快照，202512版）
  S4  學務處「休（退）學退費標準」頁面（快照）
  L1  同一個教務處頁面的現場（2026-11-13）
  L4  同一個退費標準頁面的現場（2026-11-13，靜態抓取）

用法（專案根目錄，不上網）：
  python evaluation/leave_of_absence/build_gold.py
輸出：evaluation/leave_of_absence/gold.json、sources/snapshot/*.txt
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
FORM_URL = "https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-03-02"
REFUND_URL = "https://osa.nccu.edu.tw/tw/生活事務暨僑生輔導組/學生生活事務/休退學暨研究生畢業退費/休-退-學退費標準"

SNAP_AS_OF = "2026-08（output/ 快照）"
FORM_AS_OF = "2026-08（output/ 快照；表單版本 202512版）"
LIVE_AS_OF = "2026-11-13（現場）"

SNAP = {   # 代號: (資料夾, jsonl 檔, 網址, 複本檔名, as_of)
    "S1": ("aca", "extracted_texts.jsonl", PAGE_URL, "aca_leave_page.txt", SNAP_AS_OF),
    "S2": ("aca", "extracted_texts.jsonl", LAW_URL, "aca_rules_law01A.txt", SNAP_AS_OF),
    "S3": ("aca", "extracted_supplementary.jsonl", FORM_URL, "moltke_form_QP-T01-03-02.txt", FORM_AS_OF),
    "S4": ("osa", "extracted_texts.jsonl", REFUND_URL, "osa_refund_standard.txt", SNAP_AS_OF),
}
LIVE = {   # 代號: (網址, 檔名, as_of)
    "L1": (PAGE_URL, "aca_leave_page.html", LIVE_AS_OF),
    "L4": (REFUND_URL, "osa_refund_standard.html", LIVE_AS_OF),
}


def norm(s: str) -> str:
    return re.sub(r"[\s|]+", "", unicodedata.normalize("NFKC", s or ""))


def snapshot_record(folder: str, fname: str, url: str) -> dict:
    for line in (ROOT / "output" / folder / fname).open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("url") == url:
            return d
    raise SystemExit(f"找不到快照頁面：{url}（{folder}/{fname}）")


LINK = lambda text, fid: f"[{text}](https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail={fid})"  # noqa: E731

# 每個 keypoint 的原文依據：(逐字引句, 來源代號)，優先順序高的在前。K 開頭是規定與程序，R 是退費，其餘見下
REFS = {
    "K1": [("申請當學期休學者，請於期末考試（休學截止日）前提出，逾期不予受理", "S3"),
           ("學生申請當學期休學者，須於期末考試以前辦理，逾期不予受理", "S1"),
           ("申請當學期休學者，須於期末考試以前辦理，逾期不予受理", "S2"),
           ("學生申請當學期休學者，須於期末考試以前辦理，逾期不予受理", "L1")],
    "K2": [("休學得一次申請一學期至二學年", "S3"), ("申請休學，得由學校一次核准一學期至二學年", "S1"), ("得由學校一次核准一學期至二學年", "S2")],
    "K3": [("休學累計以二學年為原則", "S3"), ("休學累計以二學年為原則", "S1"), ("休學累計以二學年為原則", "S2")],
    "K4": [("期滿因重病或特殊事故需再申請延長休學一學期或一學年者，得專案報請 校長核准", "S3"),
           ("得專案報請校長核准", "S1"), ("得專案報請校長核准", "S2")],
    "K5": [("申請延長休學以一次為原則", "S3"), ("申請延長休學以一次為原則", "S1"), ("申請延長休學以一次為原則", "S2")],
    "K6": [("請准休學學生，其休學期間之修課紀錄予以刪除（含國內外校際選課）", "S3"),
           ("請准休學學生，其休學期間之修課紀錄予以刪除", "S1"), ("請准休學學生，其休學期間之修課紀錄予以刪除", "S2")],
    "K7": [("(未成年學生須經法定代理人簽章同意。）", "S3")],
    "K8": [("※轉系(所)經核准公告後，於申辦當學期 休學者，取消其轉系(所)核准資格", "S3")],
    "K9": [("表單編號：QP-T01-03-02", "S3"), (LINK("休學/保留學籍申請書", "QP-T01-03-02"), "S1"), (LINK("休學/保留學籍申請書", "QP-T01-03-02"), "L1")],
    "K11": [("本人攜帶學生證或身分證件正本", "S1"), ("本人攜帶學生證或身分證件正本", "L1")],
    "K12": [("非本人親辦，需附委託書及被委託人身分證件正本", "S1"), ("非本人親辦，需附委託書及被委託人身分證件正本", "L1"),
            ("申請人或代辦人簽章 (須附委託書)", "S3")],
    "K14": [("會 簽 程 序 【 申 請 者 請 參 閱 本 表 說 明 並 依 序 前 往 辦 理 】", "S3")],
    "K15": [("（1）系所簽章", "S3"), ("（各系所辦公室）", "S3"), ("依說明至系所及各處室蓋章後", "S1")],
    "K16": [("（2）圖書館", "S3"), ("（總圖或分館借還書櫃檯）", "S3")],
    "K17": [("（3）出納組", "S3"), ("(行政大樓5樓) (確認學生帳戶)", "S3")],
    "K18": [("（4）住宿組", "S3"), ("限住宿生(行政大樓 3 樓)", "S3"), ("(非住宿生免辦)", "S3")],
    "K19": [("(5)生僑組/原資中心", "S3"), ("(僑生、港澳生、陸生至生僑組)", "S3")],
    "K20": [("(5)生僑組/原資中心", "S3"), ("(原住民族籍學生至原資中心)", "S3")],
    "K21": [("（6）國際合作事務處", "S3"), ("限國際學生(行政大樓8樓)", "S3")],
    "K22": [("(7）教務處註冊組", "S3"), ("擬准予□休學□保留學籍 計 學年 學期", "S3")],
    "K23": [("註冊組 組 長", "S3")],
    "K24": [("教務長 批 示", "S3")],
    "K25": [("填妥「休學/保留學籍申請書」並依說明至系所及各處室蓋章後，送至教務處註冊組", "S1"),
            ("填妥「休學/保留學籍申請書」並依說明至系所及各處室蓋章後，送至教務處註冊組", "L1")],
    "K26": [("畢業、休學、退學或轉學住宿生應於發生 日起7日內(含例假日、且不得超過當學期期 末所定離舍日)向住宿組辦理退離宿手續 後，始得申請退還宿費及住宿保證金", "S3")],
    "K27": [("在台居留事由為「就讀」者，其外僑居留 證將由移民署註銷", "S3")],
    "K28": [("學生需在辦理完休學/保 留學籍手續後10日內離境", "S3")],
    "K29": [("台灣獎學金受獎人獎學金將自休學/保留學 籍生效日之隔月開始停發", "S3")],
    "K30": [("□三個工作天後親自至註冊組承辦人處領取", "S3")],
    "K31": [("□郵寄回申請人（請附足資回郵信封）", "S3")],
    "K32": [("□不需證明書 （自行上iNCCU/校務系統Web入口/學生資訊系統/資訊服務/學年(期)學籍狀態查詢）", "S3")],
    "K33": [("繳費截止日(含)前完成休(退)學程序。學雜費全額退費(不含學生平安保險費)", "S4"),
            ("繳費截止日(含)前完成休(退)學程序。學雜費全額退費(不含學生平安保險費)", "L4")],
    "K34": [("繳費截止日次日起至學期1 / 3退費基準日完成休(退)學程序。退2 / 3學雜費 (不含學生平安保險費)", "S4"),
            ("繳費截止日次日起至學期1 / 3退費基準日完成休(退)學程序。退2 / 3學雜費 (不含學生平安保險費)", "L4")],
    "K35": [("學期1 / 3退費基準日次日起至學期2 / 3退費基準日(含)完成休(退)學程序。退1 / 3 學雜費 (不含學生平安保險費)", "S4"),
            ("學期1 / 3退費基準日次日起至學期2 / 3退費基準日(含)完成休(退)學程序。退1 / 3 學雜費 (不含學生平安保險費)", "L4")],
    "K36": [("逾學期2 / 3退費基準日申請休(退)學。學雜費全數不予退還", "S4"), ("逾學期2 / 3退費基準日申請休(退)學。學雜費全數不予退還", "L4")],
    "K37": [("另學生於休學當學期繳交平安保險費仍受學生團保之保障，故平安保險費不退費", "S4"),
            ("另學生於休學當學期繳交平安保險費仍受學生團保之保障，故平安保險費不退費", "L4")],
    "K38": [("退費相關事宜由學務處生僑組承辦", "S1"), ("退費相關事宜由學務處生僑組承辦", "L1")],
    "K39": [("學務處生僑組將依註冊組學籍資料及出納組繳費資料主動退費，學生不需親自到生僑組辦理，退費款項會直接匯入學生第一銀行或郵局帳戶", "S4"),
            ("學務處生僑組將依註冊組學籍資料及出納組繳費資料主動退費，學生不需親自到生僑組辦理，退費款項會直接匯入學生第一銀行或郵局帳戶", "L4")],
    "K40": [("宿費及住宿保證金退費，請填妥退宿申請表，並至宿舍區檢查寢室後，再到行政大樓三樓學務處住宿組辦理退費", "S4"),
            ("宿費及住宿保證金退費，請填妥退宿申請表，並至宿舍區檢查寢室後，再到行政大樓三樓學務處住宿組辦理退費", "L4")],
    "K41": [("學生未於本校登錄入帳帳戶者，請攜帶本人第一銀行或郵局帳戶至行政大樓五樓總務處出納組登錄，以利辦理退費", "S4"),
            ("學生未於本校登錄入帳帳戶者，請攜帶本人第一銀行或郵局帳戶至行政大樓五樓總務處出納組登錄，以利辦理退費", "L4")],
    "K42": [("如因經濟因素申請休學之學生，申請前可洽學務處生僑組申請各種濟助措施", "S3")],
    "K43": [("如因懷孕或終止懷孕等因素申請休學之學生，可與學務處身心健康中心討論相關醫療資源", "S3")],
    "K44": [("電話：8237-7419", "S3")],
    "K45": [("休學、保留學籍期間得於每學期註冊截止日前至總務處出納組臨櫃繳交平安保險費，投保本校學生團體平安保險", "S3")],
    "K46": [("當學期繳費註冊截止日前：申請休學或保留學籍，免繳註冊相關費用", "S1"),
            ("當學期繳費註冊截止日前：申請休學或保留學籍，免繳註冊相關費用", "L1")],
    "K47": [("繳費註冊截止日後申請休學或保留學籍者，須繳費後始得辦理", "S2"),
            ("入學第一學期之繳費註冊截止日後：申請休學或保留學籍，須繳費後始得辦理", "S1"),
            ("入學第一學期之繳費註冊截止日後：申請休學或保留學籍，須繳費後始得辦理", "L1")],
    "K48": [("若延誤註冊逾二週仍未完成繳費註冊、休學或保留學籍者，當學年度入學新生即令註銷學籍", "S1"),
            ("若延誤註冊逾二週仍未完成繳費註冊、休學或保留學籍者，當學年度入學新生即令註銷學籍", "L1")],
}


def main() -> int:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    texts, urls, as_of = {}, {}, {}
    for key, (folder, fname, url, out, ao) in SNAP.items():
        rec = snapshot_record(folder, fname, url)
        texts[key], urls[key], as_of[key] = rec["text"], url, ao
        (SNAP_DIR / out).write_text(
            f"# 來源：{url}\n# 檔案：output/{folder}/{fname}\n# 資料日期：{ao}\n# 以下為該筆記錄的 text 欄位全文（逐字複本）\n\n{rec['text']}\n",
            encoding="utf-8")
    for fname in ("aca_leave_page.html", "osa_refund_standard.html", "osa_refund_standard.html.headers.txt", "aca_leave_page.html.headers.txt"):
        if not (LIVE_DIR / fname).exists():          # 現場頁面（2026-11-13）與登記表用同一份，不重抓
            shutil.copy(REG_LIVE / fname, LIVE_DIR / fname)
    for key, (url, fname, ao) in LIVE.items():
        texts[key], urls[key], as_of[key] = html_to_text((LIVE_DIR / fname).read_text(encoding="utf-8", errors="ignore")), url, ao

    for kid, refs in REFS.items():
        for text, src in refs:
            if norm(text) not in norm(texts[src]):
                raise SystemExit(f"找不到原文，中止：[{kid}] {text!r} 不在 {src}（{urls[src]}）")

    def refs(kid):
        return [{"text": t, "source_url": urls[s], "source_kind": "live" if s.startswith("L") else "snapshot", "as_of": as_of[s]}
                for t, s in REFS[kid]]

    def semantic(kid, text, required=True, **extra):
        return {"id": kid, "text": text, "required": required, "kind": "semantic", "references": refs(kid), "acceptable_expressions": [], **extra}

    def hard(kid, text, expressions, required=True, **extra):
        return {"id": kid, "text": text, "required": required, "kind": "hard", "references": refs(kid), "acceptable_expressions": expressions, **extra}

    def registry(kid, text, reg, value_check, required=True, **extra):
        return {"id": kid, "text": text, "required": required, "kind": "hard", "value_check": value_check, "registry": reg, **extra}

    def office_pair(first_id, name, key, floor=True, unit=None, always=False):
        """單位的「找誰」與「樓層」兩個 keypoint；條件式的在答案沒提到該單位時不適用。"""
        cond = {} if always else {"conditional": True}
        extra = {} if always else {"applies_if": f"答案提到{name}"}
        out = [registry(f"K{first_id}", f"{'' if always else '答案提到' + name + '時，'}要寫出{name}任何一位的姓名或職稱加分機，或{name}的代表線",
                        {"office": key, "need": "who", **cond}, "registry_who", **extra)]
        if floor:
            reg = {"office": key, "need": "floor", **cond}
            if unit:
                reg["unit"] = unit
            out.append(registry(f"K{first_id + 1}", f"{'' if always else '答案提到' + name + '時，'}要寫出{name}的樓層", reg, "registry_floor", **extra))
        return out

    keypoints = [
        semantic("K1", "申請當學期休學要在期末考試（休學截止日）前辦理，逾期不受理"),
        semantic("K2", "休學一次可申請一學期至二學年"),
        semantic("K3", "休學累計以二學年為原則"),
        semantic("K4", "期滿因重病或特殊事故需再申請延長休學一學期或一學年者，得專案報請校長核准", required=False),
        semantic("K5", "申請延長休學以一次為原則", required=False),
        semantic("K6", "休學期間的修課紀錄予以刪除（含國內外校際選課）"),
        semantic("K7", "未成年學生須經法定代理人簽章同意"),
        semantic("K8", "轉系（所）經核准公告後，於申辦當學期休學者，取消其轉系（所）核准資格", required=False),
        hard("K9", "休學申請書的表單是「休學/保留學籍申請書」，表單編號 QP-T01-03-02", ["QP-T01-03-02"]),
        registry("K10", "休學申請書的下載連結是 " + FORM_URL, {"need": "form_link", "form": "QP-T01-03-02", "mention": "always"}, "registry_form_link"),
        semantic("K11", "辦理休學要本人攜帶學生證或身分證件正本"),
        semantic("K12", "非本人親辦，需附委託書及被委託人的身分證件正本", required=False),
        registry("K13", "答案提到委託書時，要附委託書的連結（各項證明文件申辦委託書，QP-T01-02-05）",
                 {"need": "form_link", "form": "QP-T01-02-05", "mention": "conditional"}, "registry_form_link", applies_if="答案提到委託書"),
        semantic("K14", "申請書上的會簽程序要依序前往各單位辦理"),
        semantic("K15", "要請系所簽章（各系所辦公室）"),
        semantic("K16", "要到圖書館（總圖或分館借還書櫃檯）辦理"),
        semantic("K17", "要到出納組辦理，確認學生帳戶"),
        semantic("K18", "住宿組只有住宿生需要辦理，非住宿生免辦"),
        semantic("K19", "僑生、港澳生、陸生到生僑組辦理"),
        semantic("K20", "原住民族籍學生到原住民族學生資源中心（原資中心）辦理"),
        semantic("K21", "國際合作事務處只有國際學生需要辦理"),
        semantic("K22", "教務處註冊組擬准予休學（或保留學籍）及學年學期"),
        semantic("K23", "註冊組組長簽章"),
        semantic("K24", "教務長批示"),
        semantic("K25", "各單位蓋章完畢後，送教務處註冊組"),
        semantic("K26", "住宿生要在休學事由發生日起 7 日內（不得超過當學期期末所定離舍日）向住宿組辦理退離宿手續，之後才能申請退還宿費及住宿保證金",
                 applies_if="答案提到住宿組"),
        semantic("K27", "國際學生在台居留事由為「就讀」者，外僑居留證將由移民署註銷", applies_if="答案提到國合處"),
        semantic("K28", "國際學生需在辦理完休學／保留學籍手續後 10 日內離境", applies_if="答案提到國合處"),
        semantic("K29", "台灣獎學金受獎人的獎學金將自休學／保留學籍生效日的隔月起停發", applies_if="答案提到國合處"),
        semantic("K30", "休學／保留學籍證明書可在三個工作天後親自到註冊組承辦人處領取"),
        semantic("K31", "休學／保留學籍證明書可郵寄給申請人（附足資回郵信封）", required=False),
        semantic("K32", "不需要證明書的人，可自行上 iNCCU 的學籍狀態查詢", required=False),
        semantic("K33", "繳費截止日（含）前完成休學程序，學雜費全額退費（不含學生平安保險費）"),
        semantic("K34", "繳費截止日次日起至學期 1/3 退費基準日完成休學程序，退 2/3 學雜費"),
        semantic("K35", "學期 1/3 退費基準日次日起至學期 2/3 退費基準日（含）完成休學程序，退 1/3 學雜費"),
        semantic("K36", "逾學期 2/3 退費基準日申請休學，學雜費全數不予退還"),
        semantic("K37", "學生平安保險費不退費"),
        semantic("K38", "休學退費事宜由學務處生僑組承辦"),
        semantic("K39", "完成休學程序後，生僑組依註冊組與出納組資料主動退費，款項直接匯入學生登錄的帳戶，學生不需親自辦理"),
        semantic("K40", "宿費及住宿保證金要填退宿申請表、至宿舍區檢查寢室後，到住宿組辦理退費", applies_if="答案提到住宿組"),
        semantic("K41", "未在本校登錄入帳帳戶的學生，要攜帶第一銀行或郵局帳戶到出納組登錄，才能辦理退費", required=False),
        semantic("K42", "因經濟因素申請休學的學生，申請前可洽學務處生僑組申請濟助措施", required=False),
        semantic("K43", "因懷孕或終止懷孕等因素申請休學的學生，可與學務處身心健康中心討論相關醫療資源", required=False),
        hard("K44", "身心健康中心的電話是 8237-7419", ["8237-7419"], required=False),
        semantic("K45", "休學、保留學籍期間，可在每學期註冊截止日前到出納組臨櫃繳交平安保險費，投保學生團體平安保險", required=False),
        semantic("K46", "當學期繳費註冊截止日前申請休學，免繳註冊相關費用", required=False),
        semantic("K47", "新生及轉學生在入學第一學期繳費註冊截止日後申請休學，須繳費後始得辦理", required=False),
        semantic("K48", "新生若延誤註冊逾二週仍未完成繳費註冊或休學，當學年度入學新生即令註銷學籍", required=False),
    ]
    n = 49
    for args in (
        (n, "註冊組", "registrar", True, None, True),
        (n + 2, "出納組", "cashier", True, None, False),
        (n + 4, "住宿組", "dorm", True, None, False),
        (n + 6, "生僑組", "soa", True, None, False),
        (n + 8, "原資中心", "indigenous", True, None, False),
        (n + 10, "國合處", "oic", True, "國際教育組", False),
    ):
        keypoints += office_pair(*args)

    gold = {
        "query_id": "leave_of_absence",
        "query": "如何辦理休學",
        "query_variants": [],
        "query_type": "procedure",
        "data_as_of": {
            "snapshot": SNAP_AS_OF + "；表單 " + FORM_AS_OF,
            "live": LIVE_AS_OF + "（教務處頁面、退費標準頁、各處室人員頁；人員、樓層、表單連結的現場依據在 evaluation/registry/）",
        },
        "content": (
            "辦理休學要本人攜帶學生證或身分證件正本（非本人親辦需附委託書及被委託人身分證件正本；未成年學生須經法定代理人簽章同意），"
            "填妥「休學/保留學籍申請書」（表單編號 QP-T01-03-02，" + FORM_URL + "），依會簽程序依序前往：系所簽章、圖書館、出納組（確認學生帳戶）、"
            "住宿組（限住宿生）、生僑組或原資中心（僑生、港澳生、陸生到生僑組；原住民族籍學生到原資中心）、國際合作事務處（限國際學生），"
            "再送教務處註冊組擬准，經註冊組組長簽章、教務長批示。申請當學期休學須在期末考試（休學截止日）前辦理，逾期不受理；"
            "休學一次可申請一學期至二學年，累計以二學年為原則；休學期間的修課紀錄予以刪除。"
            "休學／保留學籍證明書可三個工作天後親自到註冊組承辦人處領取，也可郵寄或自行上 iNCCU 查詢。"
            "學雜費退費：繳費截止日前完成全額退費，其後至學期 1/3 退費基準日退 2/3，至 2/3 退費基準日退 1/3，逾 2/3 不退；"
            "學生平安保險費不退。退費由學務處生僑組主動辦理並匯入已登錄的帳戶；宿費及住宿保證金要先填退宿申請表到住宿組辦理。"
        ),
        "keypoints": keypoints,
        "source_conflicts": (
            "來源優先順序：表單 > 學務處退費標準頁 > 教務處頁面 > 學則；高的是金標準。目前沒有發現來源之間互相矛盾的事實，"
            "只有詳略不同：「期末考試（休學截止日）前」（表單）與「期末考試以前」（教務處頁面、學則）意思相同；表單寫「請於…提出」，教務處頁面寫「須於…辦理」。"
            "人員頁的差異（同一分機換人、名字寫法不同）在登記表裡記錄，不在這裡。"
        ),
        "notes": [
            "人員、分機、樓層、表單連結用 registry 欄位引用 evaluation/registry/registry.json；條件式的（出納組、住宿組、生僑組、原資中心、國合處、委託書）在答案沒提到時不適用、不計入。"
            "註冊組一律必要。圖書館不列「找誰」也不列樓層（申請書只寫「總圖或分館借還書櫃檯」，沒有指定承辦人，也沒有樓層）；圖書館人員只留在登記表，答案寫出圖書館分機時不會被當成未知分機（使用者決定 2026-11-13）。",
            "蓋章的單位拆成一個單位一個 keypoint（K15–K24），生僑組與原資中心拆成兩個（K19、K20），註冊組、組長、教務長各一個（K22–K24），符合「一個 keypoint 一個事實」。",
            "選擇性（required: false）：延長休學兩項（K4、K5）、轉系取消資格（K8）、委託書內容（K12）、證明書的郵寄與自行查詢（K31、K32）、"
            "出納組登錄帳戶（K41）、使用者決定的補充說明（K42–K45：經濟因素、懷孕、身心健康中心電話 8237-7419、平安保險）、新生與轉學生註冊的三項（K46–K48）。"
            "K30（親自到註冊組領取）列為必要，是三種領取方式裡最基本的一種；這是我的暫定，待使用者確認。",
            "K44（身心健康中心電話）是 hard：8237-7419 是表單上的數字；索引裡身心健康中心主任分機是 77430，與表單不同（舊 gold 的 T08 備註），這裡只收表單寫的。",
            "不收：保留學籍的規定（這題問的是休學）、退學、後備軍人、休學與復學的其他規定（復學另有 resumption 題）、各單位內部的職掌。",
            "退費四個級距與 1/3、2/3 的算法用 semantic 判斷，不用規則：「1/3」「2/3」在時間點與比例裡都會出現，規則版會誤中。",
            "出納組舊人員頁（cashier.nccu.edu.tw）已搬到 nccuga.nccu.edu.tw（舊路徑 404），登記表以新頁面為現場來源（議題 F19）；代表線 62123（退費標準頁）與 62120（nccuga 頁尾）有現場依據。總務處 8 個新人員頁都存在 sources/live/ga_*（只有出納組與這題有關）。",
            "舊資料 evaluation/old_leave_of_absence/（56 個事實、9 站會簽）只當參考，沒有採用其中任何一條引句；這裡的引句全部重新從 output/ 與現場頁面取得。",
        ],
    }
    out = HERE / "gold.json"
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已寫入 {out.relative_to(ROOT)}（{len(keypoints)} 個 keypoint，其中 {sum(1 for k in keypoints if k.get('registry'))} 個引用登記表）")
    print(f"引句驗證通過：{len(REFS)} 個 keypoint，{sum(len(v) for v in REFS.values())} 條")
    return 0


if __name__ == "__main__":
    sys.exit(main())
