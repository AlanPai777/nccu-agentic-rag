"""
evaluation/master_double_major/build_gold.py

建「碩士班雙主修輔系申請需要經過哪些單位審核」的 gold（三段連續審核：所屬學系所 → 申請學系所 → 教務處註冊組；順序是要考的內容之一）。

原則（沿用 evaluation/README.md）：抽取，不是生成。每個 reference 的 text 必須逐字出現在來源原文裡（NFKC 正規化、忽略空白與表格線）；
寫檔前逐條驗證，任何一條找不到就中止，不寫檔。表單連結、教務處註冊組的聯絡人與樓層用 "registry" 欄位引用 evaluation/registry/registry.json。

來源（都是專屬頁面，沒有用到 FAQ 那類大而雜的頁面；優先順序：表單 > 辦法 > 教務處頁面）：
  S1  教務處「碩博士班雙修輔系」頁面（快照，output/aca/extracted_texts.jsonl）
  S2  碩博士班學生修讀雙主修、輔系辦法 law131A.pdf（快照，同上）
  S3  碩、博士班學生修讀雙主修／輔系申請表 QP-T01-03-08（快照，output/aca/extracted_supplementary.jsonl，2025-04-25 版）
  L1  同一個教務處頁面的現場（2026-11-13，curl；連結寫成 [文字](網址)）
  L2  辦法 PDF 的現場（2026-11-13，curl，pdfplumber 轉成文字）
不收：115 學年度的年度專屬公告（具體日期）、修課學分規定、放棄修讀、抵免、延長修業、學位授予、學分費（不是「審核」的問題）。

用法（專案根目錄，不上網）：
  python evaluation/master_double_major/build_gold.py
輸出：evaluation/master_double_major/gold.json、sources/snapshot/*.txt
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

PAGE_URL = "https://aca.nccu.edu.tw/zh/服務項目/雙主修-輔系-學程/碩博士班雙修輔系"
LAW_URL = "https://aca.nccu.edu.tw/download/rulesdata/law131A.pdf"
MOLTKE = "https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail="
FORM_URL = MOLTKE + "QP-T01-03-08"

SNAP_AS_OF = "2026-08（output/ 快照）"
FORM_AS_OF = "2026-08（output/ 快照；QP-T01-03-08 為 2025-04-25 版）"
LIVE_AS_OF = "2026-11-13（現場）"

SNAP = {   # 代號: (jsonl 檔, 網址, 複本檔名, as_of)
    "S1": ("extracted_texts.jsonl", PAGE_URL, "aca_double_major_page.txt", SNAP_AS_OF),
    "S2": ("extracted_texts.jsonl", LAW_URL, "aca_law131A.txt", SNAP_AS_OF),
    "S3": ("extracted_supplementary.jsonl", FORM_URL, "moltke_form_QP-T01-03-08.txt", FORM_AS_OF),
}
LIVE = {   # 代號: (網址, 檔名, as_of, 是不是 html)
    "L1": (PAGE_URL, "aca_double_major_page.html", LIVE_AS_OF, True),
    "L2": (LAW_URL, "aca_law131A.pdf.txt", LIVE_AS_OF, False),
}


def norm(s: str) -> str:
    return re.sub(r"[\s|]+", "", unicodedata.normalize("NFKC", s or ""))


def snapshot_record(fname: str, url: str) -> dict:
    for line in (ROOT / "output" / "aca" / fname).open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("url") == url:
            return d
    raise SystemExit(f"找不到快照頁面：{url}（{fname}）")


LINK = f"[國立政治大學碩、博士班學生修讀雙主修輔系申請表]({FORM_URL})"
FIRST = "經就讀學系所（學程）同意，得向招收修讀雙主修或輔系學系所（學程）提出申請"
SEND = "經就讀學系所核章後，併同其他申請資料送申請雙輔學系所審查"
INPRACT = "碩士在職專班不開放學生申請雙主修或輔系"

REFS = {
    "K1": [("是否同意所屬學生申請修讀雙主修/輔系", "S3"), (FIRST, "S2"), (FIRST, "L2"), ("經就讀學系所（學程）同意，得向招收修讀雙主修或輔系學系所（學程）提出申請", "S1"), (SEND, "S1")],
    "K2": [(SEND, "S1"), (SEND, "L1"), ("請於申請截止日前將申請表及相關申請資料紙本送達申請學系", "S3")],
    "K3": [("□准予修讀，適用規定：________學年度必修/輔系科目表 □不准修讀，原因：", "S3"), (SEND, "S1"), (SEND, "L1")],
    "K4": [("教務處註冊組", "S3"), ("(審查基本資格及維護資料)", "S3"),
           ("名單送交教務處後，仍會就說明一及說明三審查基本資格", "S3")],
    "K5": [("所屬學系(所)", "S3"), ("申請學系(所)", "S3"), ("教務處註冊組", "S3"), (SEND, "S1"),
           ("名單送交教務處後，仍會就說明一及說明三審查基本資格", "S3")],
    "K6": [("承辦人 | | 單位主管", "S3")],
    "K7": [("教務處註冊組 | 承辦人 | (審查基本資格及維護資料) | 組長", "S3")],
    "K8": [("各學系所於審核完畢後單位網頁公告核准修讀名單，請自行前往查詢", "S3")],
    "K9": [("名單送交教務處後，仍會就說明一及說明三審查基本資格；如未符資格，將取消錄取", "S3")],
    "K10": [("本校碩、博士班學生", "S1"), (INPRACT, "S1"), (INPRACT, "S2"), (INPRACT, "L1"), (INPRACT, "L2"), ("碩士在職專班學生不開放申請", "S3")],
    "K11": [("自註冊在學第二學期起至第四學期止", "S1"), ("學生自註冊在學第二學期起至第四學期止", "S2"), ("學生自註冊在學第二學期起至第四學期止", "L2"),
            ("碩、博士班學生自註冊在學第二學期起至第四學期止可申請修讀雙主修/輔系", "S3"), ("自註冊在學第二學期起至第四學期止", "L1")],
    "K12": [("每年四月下旬至五月上旬期間（依本校行事曆公告為準）", "S1"), ("每年四月下旬至五月上旬期間（依本校行事曆公告為準）", "L1"),
            ("申請日程依校訂行事曆公告為準", "S3")],
    "K13": [("學生提出申請前，請務必至教務處網頁查看學校目前有開放碩、博士班學生申請雙主修/輔系的教學單位，再向該單位提出申請", "S3"),
            ("碩、博士班雙主修輔系開辦資訊", "S1"), ("碩、博士班雙主修輔系開辦資訊", "L1")],
    "K14": [("請於申請截止日前將申請表及相關申請資料紙本送達申請學系，逾期不予受理", "S3"), ("於上列公告申請時間內填寫紙本申請書申請", "S1"),
            ("於上列公告申請時間內填寫紙本申請書申請", "L1")],
    "K15": [("申請額度以一個同級雙主修及一個同級或向下一級輔系為限", "S3"), ("修讀同級雙主修及同級或向下一級輔系，各以一學系所（學程）為限", "S1"),
            ("學生修讀同級雙主修及同級或向下一級輔系，各以一學系所（學程）為限", "S2"), ("學生修讀同級雙主修及同級或向下一級輔系，各以一學系所（學程）為限", "L2")],
    "K16": [("碩士班學生可申請修讀碩士班雙主修及碩士班輔系或學士班輔系", "S3")],
    "K17": [("同時申請同一學系為雙主修及輔系，經學系審查已符合雙主修修讀資格時，即以雙主修錄取", "S3"),
            ("同時申請同一學系為雙主修及輔系，經學系審查已符合雙主修修讀資格時，即以雙主修錄取", "S1"),
            ("學生同時申請同一學系為雙主修及輔系，經學系審查已符合雙主修修讀資格時，即以雙主修錄取", "S2")],
    "K18": [("申請修讀輔系，以不得修習前已取得學位之學系所（學程）為原則，但經申請修讀學系所（學程）同意者，不在此限", "S1"),
            ("學生申請修讀輔系，以不得修習前已取得學位之學系所（學程）為原則，但經申請修讀學系所（學程）同意者，不在此限", "S2")],
    "K19": [("經核定同意後即自動放棄原有之雙主修或輔系修讀資格，且不得再申請回復", "S1"),
            ("視同自願放棄原有之雙主修或輔系資格，且不得再申請回復", "S3"),
            ("經核定同意後即自動放棄原有之雙主修或輔系修讀資格，且不得再申請回復", "S2")],
    "K20": [("QP-T01-03-08", "S3"), (LINK, "S1"), (LINK, "L1")],
}


def main() -> int:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    texts, urls, as_of = {}, {}, {}
    for key, (fname, url, out, ao) in SNAP.items():
        rec = snapshot_record(fname, url)
        texts[key], urls[key], as_of[key] = rec["text"], url, ao
        (SNAP_DIR / out).write_text(
            f"# 來源：{url}\n# 檔案：output/aca/{fname}\n# 資料日期：{ao}\n# 以下為該筆記錄的 text 欄位全文（逐字複本）\n\n{rec['text']}\n", encoding="utf-8")
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
        semantic("K1", "就讀（所屬）學系所要先同意所屬學生申請（核章）"),
        semantic("K2", "就讀學系所核章後，申請書連同其他申請資料，送申請修讀雙主修或輔系的學系所"),
        semantic("K3", "申請學系所審查申請，決定准予修讀或不准修讀"),
        semantic("K4", "教務處註冊組審查基本資格並維護資料"),
        semantic("K5", "順序：所屬學系所 → 申請學系所 → 教務處註冊組，三段連續審核"),
        semantic("K6", "所屬學系所與申請學系所這兩站，各有承辦人與單位主管簽核"),
        semantic("K7", "教務處註冊組這一站有承辦人與組長簽核"),
        semantic("K8", "各學系所審核完畢後，在單位網頁公告核准修讀名單", required=False),
        semantic("K9", "名單送教務處後，教務處仍會審查基本資格，不符資格會取消錄取", required=False),
        semantic("K10", "對象是碩、博士班學生，碩士在職專班不開放申請"),
        semantic("K11", "申請資格：自註冊在學第二學期起至第四學期止"),
        semantic("K12", "申請時間是每年四月下旬至五月上旬（依學校行事曆公告為準）"),
        semantic("K13", "申請前要先確認哪些學系所有開辦（教務處公告的碩、博士班雙主修輔系開辦資訊）"),
        semantic("K14", "要填寫紙本申請書，並在截止日前送達申請學系，逾期不受理"),
        semantic("K15", "申請額度：同級雙主修及同級或向下一級輔系，各以一個學系所為限"),
        semantic("K16", "碩士班學生可申請碩士班雙主修，及碩士班輔系或學士班輔系"),
        semantic("K17", "同時申請同一學系的雙主修與輔系，經審查已符合雙主修資格時，以雙主修錄取"),
        semantic("K18", "申請輔系，原則上不得修習前已取得學位的學系所（經申請學系所同意者不在此限）", required=False),
        semantic("K19", "經核定修讀後，如重新申請其他學系所，核定同意即自動放棄原有的雙主修或輔系資格，且不得再申請回復", required=False),
        {"id": "K20", "text": "申請表是「碩、博士班學生修讀雙主修／輔系申請表」，表單編號 QP-T01-03-08", "required": True, "kind": "hard",
         "references": refs("K20"), "acceptable_expressions": ["QP-T01-03-08"]},
        registry("K21", "申請表的下載連結是 " + FORM_URL, {"need": "form_link", "form": "QP-T01-03-08", "mention": "always"}, "registry_form_link"),
        registry("K22", "答案要寫出教務處註冊組的聯絡人：註冊組任何一位的姓名或職稱加分機", {"office": "registrar", "need": "who"}, "registry_who"),
        registry("K23", "註冊組在行政大樓四樓", {"office": "registrar", "need": "floor"}, "registry_floor"),
    ]
    gold = {
        "query_id": "master_double_major",
        "query": "碩士班雙主修輔系申請需要經過哪些單位審核",
        "query_variants": [],
        "query_type": "procedure",
        "data_as_of": {
            "snapshot": SNAP_AS_OF + "；表單 " + FORM_AS_OF,
            "live": LIVE_AS_OF + "（教務處頁面與辦法 PDF，curl；moltke 表單連結回 302 轉登入頁，沒有跟隨）；註冊組聯絡人與樓層的現場依據在 evaluation/registry/",
        },
        "content": (
            "碩、博士班學生（碩士在職專班不開放）自註冊在學第二學期起至第四學期止，要經過三段連續審核：先由「所屬（就讀）學系所」同意（承辦人、單位主管核章），"
            "再送「申請修讀雙主修或輔系的學系所」審查，決定准予或不准修讀（承辦人、單位主管），最後由「教務處註冊組」審查基本資格並維護資料（承辦人、組長）。"
            "申請前要先確認哪些學系所有開辦；申請時間是每年四月下旬至五月上旬，填紙本申請書（表單編號 QP-T01-03-08，" + FORM_URL + "），在截止日前送達申請學系，逾期不受理。"
            "各學系所審完後在網頁公告核准名單，名單送教務處後教務處仍會審查基本資格，不符資格會取消錄取。"
        ),
        "keypoints": keypoints,
        "source_conflicts": (
            "來源優先順序：表單 > 辦法 > 教務處頁面；高的是金標準。沒有發現互相矛盾的事實，只有詳略不同：辦法第 2 條寫「經就讀學系所同意，向招收修讀雙主修或輔系學系所提出申請」，"
            "頁面寫「經就讀學系所核章後，併同其他申請資料送申請雙輔學系所審查」，表單的簽核流程把三站列成表（所屬學系所 → 申請學系所 → 教務處註冊組）；三者描述的是同一件事。"
            "申請時間在頁面是「每年四月下旬至五月上旬」，表單寫「依校訂行事曆公告為準」，年度公告（115 學年度）才寫具體日期（4/30–5/6），年度專屬，不收。"
        ),
        "notes": [
            "三段連續審核：K1、K3、K4 各考一站，K5 專門考順序（所屬學系所 → 申請學系所 → 教務處註冊組），不依賴主張切法保留順序（議題 F2、F23：順序只有判斷版能抓）。",
            "每一站的簽核人：K6（兩個學系所站各有承辦人與單位主管）、K7（註冊組承辦人與組長）。系所沒有固定聯絡窗口，不收；教務處註冊組的聯絡人與樓層引用登記表（K22、K23，必要）。",
            "選擇性：K8（公告核准名單）、K9（名單送教務處後仍審查基本資格）、K18（輔系不得修習前已取得學位的學系所）、K19（重新申請自動放棄原有資格）。「必要」目前不影響評分（議題 F8、F9）。",
            "時間（K12）用 semantic（使用者決定）：寫成「4 月底到 5 月初」「每年四、五月之交」都由 Keypoint 判斷。",
            "不收：115 學年度年度公告的具體日期（4/30–5/6）、修課學分規定（雙主修至少四分之三、輔系至少三分之二）、放棄修讀、抵免學分、延長修業、學位授予、學分費、修讀他校雙主修輔系（都不是「需要經過哪些單位審核」）。",
            "這題的依據都在專屬頁面與專屬表單（沒有用到 FAQ 那類大而雜的頁面），所以「沒讀到」的風險比第 8 題低（第 8 題的 7 日內、保證金金額主要在 FAQ）。",
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
