"""
evaluation/master_transfer/build_gold.py

建「碩士班轉系所需要經過哪些單位同意」的 gold（跨處室：並行雙處室——原就讀系所與擬轉入系所兩邊同意，再送教務處複核）。

原則（沿用 evaluation/README.md）：抽取，不是生成。每個 reference 的 text 必須逐字出現在來源原文裡（NFKC 正規化、忽略空白與表格線）；
寫檔前逐條驗證，任何一條找不到就中止，不寫檔。表單連結、教務處註冊組的聯絡人與樓層用 "registry" 欄位引用 evaluation/registry/registry.json。

來源（優先順序：表單 > 學則 > 教務處頁面；衝突時高的是金標準，低的列為可替代並標出來源）：
  S1  教務處「轉系／轉所」頁面（快照，output/aca/extracted_texts.jsonl）
  S2  學則 law01A.pdf（快照），第 37 條之 1
  S3  碩士班轉系所申請書 QP-T01-05-05（快照，output/aca/extracted_supplementary.jsonl，112年11月版）
  S4  碩士班轉系所學分認定申請書 QP-T01-05-06（快照，108年1月版）
  L1  同一個教務處頁面的現場（2026-11-13，curl；連結寫成 [文字](網址)）
不收：114 學年度第 2 學期的公告（日期與名額表是學期專屬的）。

用法（專案根目錄，不上網）：
  python evaluation/master_transfer/build_gold.py
輸出：evaluation/master_transfer/gold.json、sources/snapshot/*.txt
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

PAGE_URL = "https://aca.nccu.edu.tw/zh/服務項目/學籍/轉系"
LAW_URL = "https://aca.nccu.edu.tw/download/rulesdata/law01A.pdf"
MOLTKE = "https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail="
FORM_URL = MOLTKE + "QP-T01-05-05"
CREDIT_URL = MOLTKE + "QP-T01-05-06"

SNAP_AS_OF = "2026-08（output/ 快照）"
FORM_AS_OF = "2026-08（output/ 快照；QP-T01-05-05 為 112年11月版）"
CREDIT_AS_OF = "2026-08（output/ 快照；QP-T01-05-06 為 108年1月版）"
LIVE_AS_OF = "2026-11-13（現場）"

SNAP = {   # 代號: (jsonl 檔, 網址, 複本檔名, as_of)
    "S1": ("extracted_texts.jsonl", PAGE_URL, "aca_transfer_page.txt", SNAP_AS_OF),
    "S2": ("extracted_texts.jsonl", LAW_URL, "aca_rules_law01A.txt", SNAP_AS_OF),
    "S3": ("extracted_supplementary.jsonl", FORM_URL, "moltke_form_QP-T01-05-05.txt", FORM_AS_OF),
    "S4": ("extracted_supplementary.jsonl", CREDIT_URL, "moltke_form_QP-T01-05-06.txt", CREDIT_AS_OF),
}
LIVE = {"L1": (PAGE_URL, "aca_transfer_page.html", LIVE_AS_OF)}


def norm(s: str) -> str:
    return re.sub(r"[\s|]+", "", unicodedata.normalize("NFKC", s or ""))


def snapshot_record(fname: str, url: str) -> dict:
    for line in (ROOT / "output" / "aca" / fname).open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("url") == url:
            return d
    raise SystemExit(f"找不到快照頁面：{url}（{fname}）")


LINK = lambda text, fid: f"[{text}]({MOLTKE}{fid})"  # noqa: E731
BOTH = "經原肄業所及擬轉入所雙方主管同意"

REFS = {
    "K1": [("□同意轉出本系所(組) □不同意轉出本系所(組)", "S3"), ("原就讀系所主管審核意見", "S3"),
           ("碩士班學生於修業第二學年開始前，得經原肄業所及擬轉入 所雙方主管同意後，申請轉所", "S2"),
           ("經原肆業所及擬轉入所雙方主管同意，送教務處複核後", "S1"), ("經原肆業所及擬轉入所雙方主管同意，送教務處複核後", "L1")],
    "K2": [("□同意轉入本系所(組) □不同意轉入本系所(組)", "S3"), ("擬轉入就讀系所主管審核意見", "S3"),
           ("碩士班學生於修業第二學年開始前，得經原肄業所及擬轉入 所雙方主管同意後，申請轉所", "S2"),
           ("經原肆業所及擬轉入所雙方主管同意，送教務處複核後", "S1"), ("經原肆業所及擬轉入所雙方主管同意，送教務處複核後", "L1")],
    "K3": [("申請案經學生原就讀系所及轉入所同意並送教務處複核後，註冊組據以處理學籍等後續事宜", "S3"),
           ("經原肆業所及擬轉入所雙方主管同意，送教務處複核後", "S1"), ("經原肆業所及擬轉入所雙方主管同意，送教務處複核後", "L1")],
    "K4": [("擬核准自 學年度第 學期 起轉入 系所(組)", "S3"), ("註冊組承辦人", "S3")],
    "K5": [("註冊組組長", "S3")],
    "K6": [("教務長", "S3")],
    "K7": [("(如轉入所不同 意，請逕送回原系所並通知學生。)", "S3")],
    "K8": [("碩士班學生於修業第二學年開始前，得經原肄業所及擬轉入所雙方主管同意，申請轉所，並以一次為限", "S3"),
           ("碩士班學生於修業第二學年開始前，得經原肄業所及擬轉入 所雙方主管同意後，申請轉所，並以一次為限", "S2"),
           ("碩士班（含在職專班）學生於修業第二學年開始前", "S1"), ("碩士班（含在職專班）學生於修業第二學年開始前", "L1")],
    "K9": [("並以一次為限", "S3"), ("並以一次為限", "S2"), ("並以一次為限", "S1"), ("並以一次為限", "L1")],
    "K10": [("上學期為12月1日至12月31日止", "S3"), ("每學年12月1日至12月31日及6月1日至6月30日", "S1"), ("每學年12月1日至12月31日及6月1日至6月30日", "L1")],
    "K11": [("下學期為6月1日至6月30日止", "S3"), ("每學年12月1日至12月31日及6月1日至6月30日", "S1"), ("每學年12月1日至12月31日及6月1日至6月30日", "L1")],
    "K12": [("一般研究所學生與在職專班學生不得互轉", "S3"), ("一般研究所學生與在職專班學生不得互轉", "S1"), ("一般研究所學生與在職專班學生不得互轉", "L1")],
    "K13": [("系所經報教育部核備有學籍分組者得申請轉組", "S3"), ("系所經報教育部同意核備有學籍分組者得申請轉組", "S1"), ("系所經報教育部同意核備有學籍分組者得申請轉組", "L1")],
    "K14": [("碩士班辦理轉所之規定，由各所自訂並明列於修業規定中", "S3"), ("碩士班辦理轉所之規定，由各所自訂並明列於修業規定中", "S2"),
            ("碩士班辦理轉系所之規定，由各系所自訂並明列於修業規定中", "S1"), ("碩士班辦理轉系所之規定，由各系所自訂並明列於修業規定中", "L1")],
    "K15": [("學生申請轉所當學期不得休學", "S3"), ("學生申請轉所當學期不得休學", "S1"), ("學生申請轉所當學期不得休學", "L1")],
    "K16": [("若於申請核准後，辦理休學者，其轉所自始無效", "S3"), ("若於申請核准後，辦理休學者，其轉所自始無效", "S1"), ("若於申請核准後，辦理休學者，其轉所自始無效", "L1")],
    "K17": [("並不得再申請更改或轉回原所", "S3"), ("並不得再申請更改或轉回原所", "S2"), ("並不得再申請更改或轉回原所", "S1"), ("並不得再申請更改或轉回原所", "L1")],
    "K18": [("轉所於新學期生效", "S3"), ("轉所於新學期生效", "S1"), ("轉所於新學期生效", "L1")],
    "K19": [("學生應於轉所生效當學期開學日起二週內填寫學分認定申請書並附成績單", "S3"),
            ("學生申請轉系經核准後，於轉系生效當學期開學日起二週內辦理學分認定，請將本表填寫完畢，並附成績單", "S4"),
            ("學生應於轉所生效當學期開課日起二週內填寫「學分認定申請書」並附成績單", "S1"),
            ("學生應於轉所生效當學期開課日起二週內填寫「學分認定申請書」並附成績單", "L1")],
    "K20": [("送轉入系所辦理 學分認定審核", "S3"), ("請將本表填寫完畢，並附成績單，送轉系系所審核", "S4"),
            ("送轉入系所辦理學分認定審核", "S1"), ("送轉入系所辦理學分認定審核", "L1")],
    "K21": [("各所錄取轉所之名額，以其當學年度經核定之招生名額一成為原則", "S2")],
    "K22": [("陸生轉系所應在當學年度部定招收陸生之總名額及系所範圍內辦理流用", "S1"), ("陸生轉系所應在當學年度部定招收陸生之總名額及系所範圍內辦理流用", "L1")],
    "K23": [("碩士班甄試管道入學之學生、外國學生、僑生（含港澳生）是否得以轉系所，由各系所自行規範", "S1"),
            ("碩士班甄試管道入學之學生、外國學生、僑生（含港澳生）是否得以轉系所，由各系所自行規範", "L1")],
    "K24": [("表單編號：QP-T01-05-05", "S3"), (LINK("碩士班轉系所申請書", "QP-T01-05-05"), "S1"), (LINK("碩士班轉系所申請書", "QP-T01-05-05"), "L1")],
    "K29": [("學生原就讀系所應於每學期結束日前將表單正本送教務處註冊組", "S1"), ("學生原就讀系所應於每學期結束日前將表單正本送教務處註冊組", "L1")],
}


def main() -> int:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    texts, urls, as_of = {}, {}, {}
    for key, (fname, url, out, ao) in SNAP.items():
        rec = snapshot_record(fname, url)
        texts[key], urls[key], as_of[key] = rec["text"], url, ao
        (SNAP_DIR / out).write_text(
            f"# 來源：{url}\n# 檔案：output/aca/{fname}\n# 資料日期：{ao}\n# 以下為該筆記錄的 text 欄位全文（逐字複本）\n\n{rec['text']}\n", encoding="utf-8")
    for key, (url, fname, ao) in LIVE.items():
        texts[key], urls[key], as_of[key] = html_to_text((LIVE_DIR / fname).read_text(encoding="utf-8", errors="ignore")), url, ao

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
        semantic("K1", "要經過原就讀（原肄業）系所主管同意轉出"),
        semantic("K2", "要經過擬轉入系所主管同意轉入（和原就讀系所是兩邊都要同意）"),
        semantic("K3", "原就讀系所與轉入系所雙方都同意後，要送教務處複核"),
        semantic("K4", "教務處審核：註冊組承辦人擬核准轉入"),
        semantic("K5", "教務處審核：註冊組組長"),
        semantic("K6", "教務處審核：教務長"),
        semantic("K7", "轉入所不同意時，申請書逕送回原系所並通知學生", required=False),
        semantic("K8", "要在修業第二學年開始前申請"),
        semantic("K9", "轉所以一次為限"),
        semantic("K10", "上學期的申請期間是 12 月 1 日至 12 月 31 日"),
        semantic("K11", "下學期的申請期間是 6 月 1 日至 6 月 30 日"),
        semantic("K12", "一般研究所學生與在職專班學生不得互轉"),
        semantic("K13", "系所經報教育部核備有學籍分組者，得申請轉組", required=False),
        semantic("K14", "碩士班轉所的規定由各所自訂，並明列於修業規定中"),
        semantic("K15", "申請轉所的當學期不得休學"),
        semantic("K16", "申請核准後如果辦理休學，轉所自始無效"),
        semantic("K17", "轉所核准後，不得再申請更改或轉回原所"),
        semantic("K18", "轉所在新學期生效"),
        semantic("K19", "轉所生效後二週內，要填寫學分認定申請書並附成績單"),
        semantic("K20", "學分認定申請書送轉入系所審核"),
        semantic("K21", "各所錄取轉所的名額，以當學年度核定招生名額的一成為原則", required=False),
        semantic("K22", "陸生轉所要在當學年度部定招收陸生的總名額及系所範圍內辦理流用", required=False),
        semantic("K23", "碩士班甄試入學的學生、外國學生、僑生（含港澳生）是否能轉所，由各系所自行規範", required=False),
        {"id": "K24", "text": "申請書的表單是「碩士班轉系所申請書」，表單編號 QP-T01-05-05", "required": True, "kind": "hard",
         "references": refs("K24"), "acceptable_expressions": ["QP-T01-05-05"]},
        registry("K25", "碩士班轉系所申請書的下載連結是 " + FORM_URL, {"need": "form_link", "form": "QP-T01-05-05", "mention": "always"}, "registry_form_link"),
        registry("K26", "答案提到學分認定申請書時，要附它的連結（碩士班轉系所學分認定申請書，QP-T01-05-06）",
                 {"need": "form_link", "form": "QP-T01-05-06", "mention": "conditional"}, "registry_form_link", applies_if="答案提到學分認定申請書"),
        registry("K27", "答案要寫出教務處註冊組的聯絡人：註冊組任何一位的姓名或職稱加分機", {"office": "registrar", "need": "who"}, "registry_who"),
        registry("K28", "註冊組在行政大樓四樓", {"office": "registrar", "need": "floor"}, "registry_floor"),
        semantic("K29", "申請書經同意與複核後，學生原就讀系所要在每學期結束日前，把表單正本送教務處註冊組", required=False),
    ]
    gold = {
        "query_id": "master_transfer",
        "query": "碩士班轉系所需要經過哪些單位同意",
        "query_variants": [],
        "query_type": "procedure",
        "data_as_of": {
            "snapshot": SNAP_AS_OF + "；表單 " + FORM_AS_OF,
            "live": LIVE_AS_OF + "（教務處頁面，curl；兩個 moltke 表單連結回 302 轉登入頁，沒有跟隨）；註冊組聯絡人與樓層的現場依據在 evaluation/registry/",
        },
        "content": (
            "碩士班學生要在修業第二學年開始前申請轉所，以一次為限，並且要經過「原就讀系所主管」與「擬轉入系所主管」兩邊都同意（兩個系所並行同意，"
            "不是先後），申請書（表單編號 QP-T01-05-05，" + FORM_URL + "）再送教務處複核：註冊組承辦人擬核准、註冊組組長、教務長。"
            "如果轉入所不同意，申請書逕送回原系所並通知學生。申請期間上學期是 12 月 1 日至 12 月 31 日，下學期是 6 月 1 日至 6 月 30 日；"
            "一般研究所與在職專班學生不得互轉；申請當學期不得休學，核准後辦理休學則轉所自始無效；核准後不得再申請更改或轉回原所；"
            "轉所於新學期生效，生效後二週內要填學分認定申請書並附成績單，送轉入系所審核。"
        ),
        "keypoints": keypoints,
        "source_conflicts": (
            "來源優先順序：表單 > 學則 > 教務處頁面；高的是金標準。沒有發現互相矛盾的事實，只有措辭差異：學分認定的起算日，表單與學則寫「開學日起二週內」，"
            "教務處頁面寫「開課日起二週內」（同樣是二週，起算日措辭不同，K19 的重點是「二週內」）；「原肄業所」（學則、表單）與「原肆業所」（教務處頁面）是同一個詞的不同寫法；"
            "申請期間在表單與頁面是 12/1–12/31 與 6/1–6/30，學期專屬的公告（114 學年度第 2 學期）只寫 6/1–6/30，因為那是那一學期要開放的期間，不收。"
        ),
        "notes": [
            "並行雙處室：K1 與 K2 是兩邊同意（兩個系所並行，不是先後），K3 是兩邊都同意後才送教務處；教務處審核的三道簽章（K4–K6）在兩邊同意之後。",
            "系所沒有固定聯絡窗口（各系所自己處理），不收系所的聯絡人與樓層；教務長沒有人名，不收。教務處註冊組的聯絡人與樓層引用登記表（K27、K28，必要）。",
            "日期（K10、K11）用 semantic（使用者決定 2026-11-13）：寫成「12/1~12/31」「十二月整個月」都由 Keypoint 判斷，不用規則比對寫法。",
            "選擇性：K7、K13、K21、K22、K23、K29。轉入所不同意、轉組、名額一成、陸生名額、甄試入學外國生僑生由系所規範是補充；K29 是頁面「申請程序」寫的行政細節。「必要」目前不影響評分（議題 F8、F9）。",
            "學分認定那一段拆成 K18（新學期生效）、K19（二週內填學分認定申請書並附成績單）、K20（送轉入系所審核），符合「一個 keypoint 一個事實」；K26（學分認定申請書連結）是條件式：答案提到才要附連結。",
            "不收：114 學年度第 2 學期的公告（學期專屬的日期與名額表）、學士班轉系（不是這題）、轉校（跨校轉系所）、台聯大轉入者不得轉所（學則附注，不是流程）。",
            "兩張表單的連結現場回 302 轉登入頁（2026-11-13，curl，沒有跟隨），連結本身有效、看不到表單內容；表單內容以快照為準。記錄見 sources/live/live_check.md 與登記表。",
        ],
    }
    out = HERE / "gold.json"
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已寫入 {out.relative_to(ROOT)}（{len(keypoints)} 個 keypoint，其中 {sum(1 for k in keypoints if k.get('registry'))} 個引用登記表）")
    print("引句驗證通過：" + f"{len(REFS)} 個 keypoint，{sum(len(v) for v in REFS.values())} 條")
    return 0


if __name__ == "__main__":
    sys.exit(main())
