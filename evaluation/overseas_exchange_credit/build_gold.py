"""
evaluation/overseas_exchange_credit/build_gold.py

建「出國交換學分抵免，體育、通識、外文通識分別送哪個單位」的 gold（條件分岔：依科目類別送不同審查單位，再回到系所與教務處）。

原則（沿用 evaluation/README.md）：抽取，不是生成。每個 reference 的 text 必須逐字出現在來源原文裡（NFKC 正規化、忽略空白與表格線）；
寫檔前逐條驗證，任何一條找不到就中止，不寫檔。表單連結、各單位的聯絡人與樓層用 "registry" 欄位引用 evaluation/registry/registry.json。

來源（都是專屬頁面，沒有用到 FAQ 那類大而雜的頁面；優先順序：表單 > 辦法 > 教務處頁面）：
  S1  教務處「學分抵免（含新生及出國）」頁（快照，output/aca/extracted_texts.jsonl）；本題只用「出國交換」段
  S2  學生抵免學分辦法 law06A.pdf（快照，同上；民國 115 年 7 月 30 日發布版）
  S3  國內／出國交換選課學分抵免申請書 QP-T01-04-05（快照，output/aca/extracted_supplementary.jsonl，201909 修訂 8 版）
  S4  通識教育中心「國外交換學分認抵本校一般通識學分」頁（快照，output/gecenter/extracted_texts.jsonl）
  S5  通識教育中心 FAQ qa38（快照，同上，沒有現場）
  L1  同一個教務處頁面的現場（2026-11-14，curl；連結寫成 [文字](網址)）
  L2  辦法 PDF 的現場（2026-11-14，curl，pdfplumber 轉成文字）
  L4  通識教育中心頁面的現場（2026-11-14，curl；網址要加結尾斜線，不加的回 301，兩次回應都存著）
不收：新生抵免、暑期交換、國內交換（台北藝大、台聯大）、雙聯學位（law91A）、中文通識（表單寫個案審查，辦法寫中文系審查，題目沒問）、
      逾期未辦理的處理、抵免學分數上限（二分之一、三分之一）、學分班。

用法（專案根目錄，不上網）：
  python evaluation/overseas_exchange_credit/build_gold.py
輸出：evaluation/overseas_exchange_credit/gold.json、sources/snapshot/*.txt
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

PAGE_URL = "https://aca.nccu.edu.tw/zh/服務項目/成績-抵免/學分抵免（含新生及出國）-整合"
LAW_URL = "https://aca.nccu.edu.tw/download/rulesdata/law06A.pdf"
MOLTKE = "https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail="
FORM_URL = MOLTKE + "QP-T01-04-05"

SNAP_AS_OF = "2026-08（output/ 快照）"
FORM_AS_OF = "2026-08（output/ 快照；QP-T01-04-05 為 201909 修訂 8 版）"
LIVE_AS_OF = "2026-11-14（現場）"

GEC_URL = "https://gecenter.nccu.edu.tw/student-zone/gec-credit-waiver/credits-from-overseas-exchange-programs"
GEC_FAQ_URL = "https://gecenter.nccu.edu.tw/faq/qa38"
SNAP = {   # 代號: (子網域, jsonl 檔, 網址, 複本檔名, as_of)
    "S1": ("aca", "extracted_texts.jsonl", PAGE_URL, "aca_credit_page.txt", SNAP_AS_OF),
    "S2": ("aca", "extracted_texts.jsonl", LAW_URL, "aca_law06A.txt", SNAP_AS_OF),
    "S3": ("aca", "extracted_supplementary.jsonl", FORM_URL, "moltke_form_QP-T01-04-05.txt", FORM_AS_OF),
    "S4": ("gecenter", "extracted_texts.jsonl", GEC_URL, "gecenter_overseas_credit_page.txt", SNAP_AS_OF),
    "S5": ("gecenter", "extracted_texts.jsonl", GEC_FAQ_URL, "gecenter_faq_qa38.txt", SNAP_AS_OF),
}
LIVE = {   # 代號: (網址, 檔名, as_of, 是不是 html)
    "L1": (PAGE_URL, "aca_credit_page.html", LIVE_AS_OF, True),
    "L2": (LAW_URL, "aca_law06A.pdf.txt", LIVE_AS_OF, False),
    "L4": (GEC_URL + "/", "gec_overseas_credit_page_slash.html", LIVE_AS_OF, True),
}


def norm(s: str) -> str:
    return re.sub(r"[\s|]+", "", unicodedata.normalize("NFKC", s or ""))


def snapshot_record(sub: str, fname: str, url: str) -> dict:
    for line in (ROOT / "output" / sub / fname).open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("url") == url:
            return d
    raise SystemExit(f"找不到快照頁面：{url}（{sub}/{fname}）")


LINK = f"[國內/出國交換選課學分抵免申請表]({FORM_URL})"
SEND = "填具本校出國選課抵免學分申請表，併同出國學年期成績單正本乙份及課程大綱等相關文件，逕至各系所辦公室送件申請"
FIRST = "擬申請抵免科目如須校內相關開課單位審查（如中文通識、外文通識、體育、一般通識及雙主修輔系課程），應先行送審"
UNITS3 = "將由就讀系所送請體育室、通識教育中心及外文中心審定"
FLOW = "本項各類抵免學分經相關單位審核後，送交教務處註冊組複查，簽請教務長核定後，於學生學業成績總表登錄"

REFS = {
    "K1": [("表單編號:QP-T01-04-05", "S3"), (LINK, "S1"), (LINK, "L1")],
    "K3": [("逕至各系所辦公室送件申請", "S1"), ("逕至各系所辦公室送件申請", "L1"), ("向就讀系辦理學分抵免申請", "S3")],
    "K4": [("併同出國學年期成績單正本乙份", "S1"), ("併同出國學年期成績單正本乙份", "L1"),
           ("應出具於交換大學修習之全部科目含學分數之正式成績單或成績證明書", "S3")],
    "K5": [("課程大綱等相關文件", "S1"), ("課程大綱等相關文件", "L1"), ("各審查單位得要求學生檢附課程大綱，始予受理", "S2"),
           ("各審查單位得要求學生檢附課程大綱，始予受理", "L2")],
    "K6": [("申請出國選課學年期之次學期三分之一基準日前辦理", "S1"), ("申請出國選課學年期之次學期三分之一基準日前辦理", "L1"),
           ("於次學期三分之一基準日前向就讀系辦理學分抵免申請", "S3")],
    "K7": [(FIRST, "S1"), (FIRST, "L1")],
    "K8": [("體育課程由體育室審查", "S2"), ("體育課程由體育室審查", "L2"), (UNITS3, "S3")],
    "K9": [("一般通識及書院通識由通識教育中心審查", "S2"), ("一般通識及書院通識由通識教育中心審查", "L2"), (UNITS3, "S3"),
           ("於次學期三分之一基準日前洽通識教育中心辦理", "S4"), ("於次學期三分之一基準日前洽通識教育中心辦理", "L4"),
           ("經通識教育中心審查通過者，即可將交換學校所修課程抵免為本校一般通識學分", "S5")],
    "K18": [("國外學校含有及格成績之成績證明，回國後須至系所或國合處蓋「與正本相符」戳記", "S4"),
            ("國外學校含有及格成績之成績證明，回國後須至系所或國合處蓋「與正本相符」戳記", "L4")],
    "K19": [("欲抵免之政大課程大綱，須為近十年內開設之一般通識課程（核心通識不得抵免）", "S4"),
            ("欲抵免之政大課程大綱，須為近十年內開設之一般通識課程（核心通識不得抵免）", "L4"),
            ("核心與書院通識皆不可拿來認抵", "S5")],
    "K10": [("外文通識由外文中心審查", "S2"), ("外文通識由外文中心審查", "L2"), (UNITS3, "S3")],
    "K11": [("所修科目、學分數應否抵免列入畢業最低學分總數內計算，由就讀系所自行認定", "S3"), ("專業課程由學生就讀學系所審查", "S2"),
            ("專業課程由學生就讀學系所審查", "L2")],
    "K12": [(FLOW, "S2"), (FLOW, "L2"), ("送交各系所審查後由註冊組核辦", "S3")],
    "K13": [(FLOW, "S2"), (FLOW, "L2")],
    "K14": [(FLOW, "S2"), (FLOW, "L2"), ("經審查「同意抵免」之科目於教務處核定後登錄於本校成績總表", "S3")],
    "K15": [(FLOW, "S2"), (FLOW, "L2"), ("經審查「同意抵免」之科目於教務處核定後登錄於本校成績總表", "S3")],
    "K16": [(FLOW, "S2"), (FLOW, "L2"), (UNITS3, "S3")],
    "K17": [("體育必修課程得申請抵免，以四門為限", "S2"), ("體育必修課程得申請抵免，以四門為限", "L2")],
}


def main() -> int:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    texts, urls, as_of = {}, {}, {}
    for key, (sub, fname, url, out, ao) in SNAP.items():
        rec = snapshot_record(sub, fname, url)
        texts[key], urls[key], as_of[key] = rec["text"], url, ao
        (SNAP_DIR / out).write_text(
            f"# 來源：{url}\n# 檔案：output/{sub}/{fname}\n# 資料日期：{ao}\n# 以下為該筆記錄的 text 欄位全文（逐字複本）\n\n{rec['text']}\n", encoding="utf-8")
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

    def unit_contact(kid_who, kid_floor, key, name, floor_text=None):
        out = [registry(kid_who, f"答案提到{name}時，要寫出{name}的聯絡人：{name}任何一位的姓名或職稱加分機",
                        {"office": key, "need": "who", "conditional": True}, "registry_who", required=False, applies_if=f"答案提到{name}")]
        if floor_text:
            out.append(registry(kid_floor, floor_text, {"office": key, "need": "floor", "conditional": True}, "registry_floor",
                                required=False, applies_if=f"答案提到{name}"))
        return out

    keypoints = [
        {"id": "K1", "text": "申請表是「國內／出國交換選課學分抵免申請表」，表單編號 QP-T01-04-05", "required": True, "kind": "hard",
         "references": refs("K1"), "acceptable_expressions": ["QP-T01-04-05"]},
        registry("K2", "申請表的下載連結是 " + FORM_URL, {"need": "form_link", "form": "QP-T01-04-05", "mention": "always"}, "registry_form_link"),
        semantic("K3", "申請書送到就讀系所辦公室（由系所辦理抵免申請）"),
        semantic("K4", "要附出國學年期成績單正本（國外大學的正式成績單或成績證明書）"),
        semantic("K5", "要附課程大綱等相關文件"),
        semantic("K6", "時限：出國選課學年期的次學期三分之一基準日前辦理"),
        semantic("K7", "科目如須校內相關開課單位審查（體育、通識、外文通識等），要先行送審"),
        semantic("K8", "體育課程抵免由體育室審查"),
        semantic("K9", "一般通識（含書院通識）抵免由通識教育中心審查"),
        semantic("K10", "外文通識抵免由外文中心審查"),
        semantic("K11", "其他科目是否抵免、列入畢業學分，由就讀系所審查認定"),
        semantic("K12", "各單位審核後，送教務處註冊組複查"),
        semantic("K13", "註冊組複查後，簽請教務長核定"),
        semantic("K14", "教務長核定後，抵免的科目登錄於學生的成績總表"),
        semantic("K15", "審查單位（體育室、通識教育中心、外文中心）審核在前，再由註冊組複查、教務長核定、登錄成績總表"),
        semantic("K16", "體育、通識、外文通識是由就讀系所送請各自的審查單位審定（體育室、通識教育中心、外文中心）", required=False),
        semantic("K17", "體育必修課程抵免以四門為限", required=False),
        semantic("K18", "向通識教育中心申請時，國外學校的成績證明要先到系所或國合處蓋「與正本相符」戳記", required=False),
        semantic("K19", "通識抵免的對象是一般通識課程，核心通識不得抵免", required=False),
        registry("K20", "答案要寫出教務處註冊組的聯絡人：註冊組任何一位的姓名或職稱加分機", {"office": "registrar", "need": "who"}, "registry_who"),
        registry("K21", "註冊組在行政大樓四樓", {"office": "registrar", "need": "floor"}, "registry_floor"),
        *unit_contact("K22", "K23", "gec", "通識教育中心", "通識教育中心在行政大樓四樓（與教務處同層）"),
        *unit_contact("K24", "", "sports", "體育室"),
        *unit_contact("K25", "K26", "flc", "外文中心", "外文中心辦公室在國際大樓（五樓，或寫辦公室 360506 室）"),
    ]
    gold = {
        "query_id": "overseas_exchange_credit",
        "query": "出國交換學分抵免，體育、通識、外文通識分別送哪個單位",
        "query_variants": [],
        "query_type": "procedure",
        "data_as_of": {
            "snapshot": SNAP_AS_OF + "；表單 " + FORM_AS_OF,
            "live": LIVE_AS_OF + "（教務處頁面、辦法 PDF 與通識中心頁面，curl；moltke 表單連結沒有送請求）；各單位聯絡人與樓層的現場依據在 evaluation/registry/",
        },
        "content": (
            "出國交換回國後，學生要在出國選課學年期的次學期三分之一基準日前，填「國內／出國交換選課學分抵免申請表」（表單編號 QP-T01-04-05，" + FORM_URL + "），"
            "連同出國學年期成績單正本與課程大綱等相關文件，送到就讀系所辦公室。科目如須校內相關開課單位審查，要先行送審："
            "體育課程由「體育室」審查，一般通識（含書院通識）由「通識教育中心」審查，外文通識由「外文中心」審查（由就讀系所送請審定）；其他科目由就讀系所審查認定。"
            "各單位審核後，送教務處註冊組複查，簽請教務長核定，再登錄於學生的成績總表。體育必修課程的抵免以四門為限。"
        ),
        "keypoints": keypoints,
        "source_conflicts": (
            "來源優先順序：表單 > 辦法 > 教務處頁面。三者沒有互相矛盾的事實，但「誰送審」的寫法不同：教務處頁面寫學生要「先行送審」（如須校內相關開課單位審查），"
            "表單附註 3 寫「將由就讀系所送請體育室、通識教育中心及外文中心審定」，辦法第 7 條只寫各類課程由哪個單位審查。"
            "通識教育中心專屬頁面寫「學生…洽通識教育中心辦理」。四處的寫法不同（先行送審、由就讀系所送請、洽通識教育中心辦理），"
            "使用者的判斷是它們說的是同一件事（哪類科目由哪個單位審查），所以 K8–K10 只考「由哪個單位審查」，不規定誰負責送；誰送審單獨成 K16（選擇性，只依表單附註 3）。"
        ),
        "notes": [
            "條件分岔：體育、一般通識、外文通識三類各自走不同的審查單位（K8、K9、K10），三個都必要。題目就是問這三類，所以沒有用 applies_if（用了的話，答案漏掉某一類反而會從分母拿掉，變成獎勵漏答）；只有聯絡人與樓層才是有條件的（議題 F8）。",
            "題目的「通識」解讀為一般通識（含書院通識）；中文通識只當留意，不收。",
            "順序：K15 專門考「審查單位審核在前，再由註冊組複查、教務長核定、登錄」；來源（辦法第 7 條）只寫到「經相關單位審核後，送註冊組複查，簽請教務長核定後登錄」，系所與審查單位之間誰先誰後，來源沒有定論（見 source_conflicts），所以 K15 只考審查單位與教務處之間的先後（議題 F2、F23）。",
            "註冊組的聯絡人與樓層（K20、K21）列為必要，延續前面幾題；三個審查單位的聯絡人與樓層（K22–K26）是選擇性，而且是有條件的：答案提到該單位才要求，沒提到就從分母拿掉。",
            "聯絡人與樓層的登記方式：登記表登錄各單位人員頁的全部人員，答案寫任何一位的姓名或職稱加正確分機都算（既有做法）。體育室 21 人裡多數是游泳館、健身房、籃球隊人員，業務與抵免無關；與抵免相關的是體育教學組（洪鈺釗、吳鴻傑）。這個落差目前不處理，登記為議題 F25。",
            "外文中心的樓層：頁面兩處說法並存（主任辦公室「國際大樓360506室」，交通位置「辦公室位於國際大樓 5 樓，大樓正門口位於 3 樓」），兩種都收；正門的 3 樓不是辦公室樓層，不收。通識教育中心沒有專屬樓層欄，樓層出處是人員頁頁尾（教務處地址）與明寫「教務處通識教育中心（行政大樓4樓）」的新聞頁；體育室頁面沒有樓層，不收。",
            "【事實補充，不是衝突】通識教育中心專屬頁面比教務處頁面更具體：向通識中心申請的國外成績證明須先到系所或國合處蓋「與正本相符」戳記（K18，選擇性），欲抵免的政大課程限一般通識、核心通識不得抵免（K19，選擇性）。教務處頁面與表單寫的是「成績單正本」（K4），那是一般性的收件要求，兩者可以同時成立。體育室與外文中心在語料裡沒有對應的專屬頁面，這兩類只能靠表單、辦法與教務處頁面。",
            "【解讀，未驗證】整張表填完後由誰送到教務處註冊組：辦法第 7 條是被動句（經相關單位審核後，送交教務處註冊組複查），表單寫「送交各系所審查後由註冊組核辦」，三個來源都沒有主詞。使用者的推測是學生自己送（系所認定的必修也要一併送），不寫入 keypoint；答案寫「學生送」或「系所轉送」都不判錯（K12 只問有沒有送註冊組複查）。",
            "中文通識：辦法第 7 條寫由中文系審查，表單附註 3 寫赴大陸地區交換的學生經審查單位中文系簽核同意逐案審查（2013-10-18）；審查單位都是中文系，題目沒問中文通識，不收。",
            "不收：新生抵免、暑期交換、國內交換、雙聯學位（law91A 是雙聯學位的作業原則，不是抵免辦法）、中文通識、成績以 EX 字樣登錄（辦法第 7 條，使用者決定先不收）、逾期未辦理的處理（不抵免切結、成績總表註記）、抵免學分上限（博碩士二分之一、學士班三分之一）、學分班。",
            "moltke 的表單連結沒有送現場請求（其他題已驗證一律 302 轉登入頁）；連結以教務處現場頁面（2026-11-14）列出的為準，表單內容以快照為準。記錄見 sources/live/live_check.md 與登記表。",
        ],
    }
    out = HERE / "gold.json"
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已寫入 {out.relative_to(ROOT)}（{len(keypoints)} 個 keypoint，其中 {sum(1 for k in keypoints if k.get('registry'))} 個引用登記表）")
    print(f"引句驗證通過：{len(REFS)} 個 keypoint，{sum(len(v) for v in REFS.values())} 條")
    return 0


if __name__ == "__main__":
    sys.exit(main())
