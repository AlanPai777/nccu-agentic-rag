"""
evaluation/cross_school_double_major/build_gold.py

建「政大學生跨校修讀台聯大雙主修需要經過哪些單位審核」的 gold（跨校的四站連續審核：原就讀學校的主修學系 → 原校註冊組 → 加修學校的加修學系 → 加修學校註冊組；順序是要考的內容之一）。

原則（沿用 evaluation/README.md）：抽取，不是生成。每個 reference 的 text 必須逐字出現在來源原文裡（NFKC 正規化、忽略空白與表格線）；
寫檔前逐條驗證，任何一條找不到就中止，不寫檔。表單連結、政大註冊組的聯絡人與樓層用 "registry" 欄位引用 evaluation/registry/registry.json。

來源（都是專屬頁面，沒有用到 FAQ 那類大而雜的頁面；優先順序：表單 > 辦法 > 教務處專區頁面）：
  S1  教務處「跨校修讀雙主修輔系」專區頁（快照，output/aca/extracted_texts.jsonl）
  S2  台灣聯合大學系統學生跨校修讀雙主修辦法（快照，同上）
  S3  台灣聯合大學系統學士班學生跨校修讀輔系/雙主修申請表 QP-T01-04-21（快照，output/aca/extracted_supplementary.jsonl，製表日期 20230331）
  L1  同一個教務處專區頁的現場（2026-11-14，curl；連結寫成 [文字](網址)）
  L2  辦法 PDF 的現場（2026-11-14，curl，pdfplumber 轉成文字）
不收：畢業資格審查（QP-T01-04-23）、放棄修讀（QP-T01-04-22）、115 學年度年度公告（具體日期）與 114 學年核定名單、學位證書加列、選課與學分費、
      國立臺北藝術大學的跨校輔系（教務處「跨校雙輔」頁，不是台聯大）、他校的雙主修輔系資訊。

用法（專案根目錄，不上網）：
  python evaluation/cross_school_double_major/build_gold.py
輸出：evaluation/cross_school_double_major/gold.json、sources/snapshot/*.txt
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

PAGE_URL = "https://aca.nccu.edu.tw/zh/專區業務/newbie-2/150-跨校修讀雙主修輔系/4963-跨校修讀雙主修輔系"
LAW_URL = "https://aca.nccu.edu.tw/db/upload/台灣聯合大學系統學生跨校修讀雙主修辦法.pdf"
MOLTKE = "https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail="
FORM_URL = MOLTKE + "QP-T01-04-21"

SNAP_AS_OF = "2026-08（output/ 快照）"
FORM_AS_OF = "2026-08（output/ 快照；QP-T01-04-21 製表日期 20230331）"
LIVE_AS_OF = "2026-11-14（現場）"

SNAP = {   # 代號: (jsonl 檔, 網址, 複本檔名, as_of)
    "S1": ("extracted_texts.jsonl", PAGE_URL, "aca_cross_school_page.txt", SNAP_AS_OF),
    "S2": ("extracted_texts.jsonl", LAW_URL, "ust_double_major_law.txt", SNAP_AS_OF),
    "S3": ("extracted_supplementary.jsonl", FORM_URL, "moltke_form_QP-T01-04-21.txt", FORM_AS_OF),
}
LIVE = {   # 代號: (網址, 檔名, as_of, 是不是 html)
    "L1": (PAGE_URL, "aca_cross_school_page.html", LIVE_AS_OF, True),
    "L2": (LAW_URL, "ust_double_major_law.pdf.txt", LIVE_AS_OF, False),
}


def norm(s: str) -> str:
    return re.sub(r"[\s|\ue000-\uf8ff]+", "", unicodedata.normalize("NFKC", s or ""))  # 私用區字元（U+E000–U+F8FF，表單簽核欄的字型符號，肉眼看不到）不算內容，兩邊都拿掉


def snapshot_record(fname: str, url: str) -> dict:
    for line in (ROOT / "output" / "aca" / fname).open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("url") == url:
            return d
    raise SystemExit(f"找不到快照頁面：{url}（{fname}）")


LINK = f"[台灣聯合大學系統學士班學生跨校修讀輔系/雙主修申請表]({FORM_URL})"
BOTH = "須經所屬及申請修讀之校系雙方同意"
KIND = "僅限申請修讀與本系性質不同之學系，並須經所屬及申請修讀之校系雙方同意"
# 表單「順序」欄的編號是私用區字元 U+F081–F084（第 1–4 站，字型符號，肉眼看不到）；比對時忽略私用區字元，所以引句寫肉眼看到的字就可以
HOME = "原就讀學校 | 主修學系 | 是否同意學生加修他校性質不同學系為輔系/雙主修"
HOME_REG = "不同意，原因： | | 承辦人 | 單位主管 | 註冊組 | 承辦人 | 組 長"
HOST = "加 修 學 校 | 加修學系 | □准予修讀，適用規定：＿ ＿學年度必修科目表 □不准修讀，意見："
HOST_REG = "不准修讀，意見： | | 承辦人 | 單位主管 | 註冊組 | 承辦人 | 組 長"

REFS = {
    "K1": [(LINK, "S1"), (LINK, "L1")],
    "K3": [("碩博士班不開放雙主修及輔系", "S1"), ("碩博士班不開放雙主修及輔系", "L1"), ("開放四校學士班學生於系統內申請跨校修讀雙主修", "S2"),
           ("開放四校學士班學生於系統內申請跨校修讀雙主修", "L2"), ("台灣聯合大學系統學士班學生跨校修讀輔系/雙主修申請表", "S3")],
    "K4": [("學士班以一年級下學期起至三年級止，學生得申請台聯大跨校雙主修及輔系，且申請學生當學期須註冊在學", "S1"),
           ("學士班以一年級下學期起至三年級止，學生得申請台聯大跨校雙主修及輔系，且申請學生當學期須註冊在學", "L1")],
    "K5": [(KIND, "S1"), (KIND, "L1"), ("申請限加修不同性質之學系為第二主修", "S2"), ("申請限加修不同性質之學系為第二主修", "L2"),
           ("前項申請限加修不同性質之學系為輔系或雙主修", "S3")],
    "K6": [(BOTH, "S1"), (BOTH, "L1"), ("申請之時，須經學生所在學校與申請加修雙主修學校同意", "S2"), ("申請之時，須經學生所在學校與申請加修雙主修學校同意", "L2")],
    "K7": [(HOME, "S3")],
    "K8": [(HOME_REG, "S3")],
    "K9": [(HOST, "S3")],
    "K10": [(HOST_REG, "S3")],
    "K11": [("順序 | 辦理單位 | | 辦理內容/簽章", "S3"), (HOME, "S3"), (HOST, "S3")],
    "K12": [("承辦人 | 單位主管", "S3"), (HOME, "S3"), (HOST, "S3")],
    "K13": [("註冊組 | 承辦人 | 組 長", "S3"), (HOME_REG, "S3"), (HOST_REG, "S3")],
    "K14": [("繳 交 文 件 | □ 中文歷年成績單 □其他規定資料", "S3")],
    "K15": [("審查結果由註冊組公告於註冊組網頁，請學生於公告時間自行至網頁查詢", "S3")],
    "K16": [("若申請外校雙主修通過，則自願自動放棄現正修習雙主修資格", "S3")],
    "K17": [("台聯大學生跨校修讀輔系及雙主修之上限(含校內輔系及雙主修)為一個雙主修及二個輔系", "S3")],
    "K18": [("原則每年5月底公告相關訊息，並於7月接受申請，8月下旬公布榜單", "S1"), ("原則每年5月底公告相關訊息，並於7月接受申請，8月下旬公布榜單", "L1")],
    "K19": [("本校學生跨校修讀雙主修不得以他校雙主修學系畢業", "S1"), ("本校學生跨校修讀雙主修不得以他校雙主修學系畢業", "L1")],
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
        {"id": "K1", "text": "申請表是「台灣聯合大學系統學士班學生跨校修讀輔系／雙主修申請表」，表單編號 QP-T01-04-21", "required": True, "kind": "hard",
         "references": refs("K1"), "acceptable_expressions": ["QP-T01-04-21"]},
        registry("K2", "申請表的下載連結是 " + FORM_URL, {"need": "form_link", "form": "QP-T01-04-21", "mention": "always"}, "registry_form_link"),
        semantic("K3", "對象是學士班學生，碩博士班不開放"),
        semantic("K4", "申請資格：學士班一年級下學期起至三年級止，申請當學期須註冊在學"),
        semantic("K5", "只能申請修讀與本系性質不同的學系"),
        semantic("K6", "申請須經原就讀學校與加修學校雙方同意"),
        semantic("K7", "原就讀學校（政大）的主修學系要先審核，同意學生加修他校性質不同的學系"),
        semantic("K8", "原就讀學校（政大）的註冊組審核"),
        semantic("K9", "加修學校的加修學系審查，決定准予或不准修讀"),
        semantic("K10", "加修學校的註冊組審核"),
        semantic("K11", "順序：原就讀學校主修學系 → 原校註冊組 → 加修學校加修學系 → 加修學校註冊組，四站連續審核"),
        semantic("K12", "兩個學系的站（原就讀學校主修學系、加修學系）各有承辦人與單位主管簽核"),
        semantic("K13", "兩個註冊組的站（原就讀學校、加修學校）各有承辦人與組長簽核"),
        semantic("K14", "要繳交中文歷年成績單", required=False),
        semantic("K15", "審查結果由註冊組公告在網頁，學生自行到網頁查詢", required=False),
        semantic("K16", "政大學生若申請外校雙主修通過，會自動放棄現在修習的（校內）雙主修資格", required=False),
        semantic("K17", "台聯大學生跨校修讀的上限（含校內）是一個雙主修及二個輔系", required=False),
        semantic("K18", "作業期間：原則每年 5 月底公告、7 月受理申請、8 月下旬公布榜單", required=False),
        semantic("K19", "政大學生跨校修讀雙主修，不得以他校的雙主修學系畢業", required=False),
        registry("K20", "答案要寫出教務處註冊組的聯絡人：註冊組任何一位的姓名或職稱加分機", {"office": "registrar", "need": "who"}, "registry_who"),
        registry("K21", "註冊組在行政大樓四樓", {"office": "registrar", "need": "floor"}, "registry_floor"),
    ]
    gold = {
        "query_id": "cross_school_double_major",
        "query": "政大學生跨校修讀台聯大雙主修需要經過哪些單位審核",
        "query_variants": [],
        "query_type": "procedure",
        "data_as_of": {
            "snapshot": SNAP_AS_OF + "；表單 " + FORM_AS_OF,
            "live": LIVE_AS_OF + "（教務處專區頁與辦法 PDF，curl；moltke 表單連結沒有送請求）；註冊組聯絡人與樓層的現場依據在 evaluation/registry/",
        },
        "content": (
            "只有學士班學生（碩博士班不開放）能申請，資格是一年級下學期起至三年級止、申請當學期註冊在學，且只能申請與本系性質不同的學系；申請須經原就讀學校與加修學校雙方同意。"
            "填「台灣聯合大學系統學士班學生跨校修讀輔系／雙主修申請表」（表單編號 QP-T01-04-21，" + FORM_URL + "），審核是兩校各兩站、共四站連續進行："
            "先由原就讀學校（政大）的「主修學系」同意（承辦人、單位主管），再由政大「註冊組」（承辦人、組長），接著由加修學校的「加修學系」決定准予或不准修讀（承辦人、單位主管），最後由加修學校的「註冊組」（承辦人、組長）。"
            "審查結果由註冊組公告在網頁，學生自行查詢。"
        ),
        "keypoints": keypoints,
        "source_conflicts": (
            "來源優先順序：表單 > 辦法 > 教務處專區頁面；高的是金標準。沒有發現互相矛盾的事實，只有詳略不同：辦法第 2 條只寫「須經學生所在學校與申請加修學校同意」，"
            "專區頁寫「須經所屬及申請修讀之校系雙方同意」，表單的簽核流程把四站列成表（原就讀學校主修學系、註冊組，加修學校加修學系、註冊組）；三者描述的是同一件事。"
            "作業期間在專區頁是「原則每年 5 月底公告、7 月受理、8 月下旬公布榜單」，115 學年度的年度公告才寫具體日期（7/1–7/23、8/31），年度專屬，不收。"
        ),
        "notes": [
            "表單簽核流程表的「順序」欄，四站各有一個編號字元（私用區字元 U+F081–F084，字型符號，肉眼看不到，抽出的文字裡是看不見的字元）；這是四站順序的直接證據；驗證比對時忽略這類私用區字元（不算內容），所以引句寫肉眼看到的字（K7–K11）。",
            "四站連續審核：K7、K8、K9、K10 各考一站，K11 專門考順序（原學系 → 原校註冊組 → 加修學系 → 加修校註冊組），不依賴主張切法保留順序（議題 F2、F23：順序只有判斷版能抓）。",
            "每一站的簽核人：K12（兩個學系站各有承辦人與單位主管）、K13（兩個註冊組站各有承辦人與組長）。加修學校是他校，登記表不登錄他校註冊組的人員；政大註冊組的聯絡人與樓層引用登記表（K20、K21，必要，延續前面幾題）。",
            "選擇性：K14（繳中文歷年成績單）、K15（結果公告在註冊組網頁）、K16（申請外校雙主修通過即自動放棄校內雙主修）、K17（上限一個雙主修及二個輔系）、K18（作業期間）、K19（不得以他校雙主修學系畢業）。「必要」目前不影響評分（議題 F8、F9）。",
            "時間（K18）用 semantic（使用者決定）：寫成「五月底公告、七月申請、八月底放榜」都由 Keypoint 判斷；115 學年度的具體日期不收。",
            "不收：畢業資格審查（QP-T01-04-23，修滿學分之後才做的另一條審核流程：原學系 → 加修學系 → 加修學校註冊組；使用者決定不收，與第 9 題不收學位授予一致）、放棄修讀（QP-T01-04-22）、115 學年度年度公告與 114 學年核定名單、學位證書加列、選課與學分費、他校的雙主修輔系資訊。",
            "【注意】教務處另有一頁「跨校雙輔」，那是與國立臺北藝術大學合作的跨校輔系（註冊組彙整發函至北藝大審查），不是台聯大，這題不用。兩者的作業方式不同，不要混用。",
            "這題的依據都在專屬頁面與專屬表單與台聯大辦法（沒有用到 FAQ 那類大而雜的頁面）。",
            "moltke 的表單連結沒有送現場請求（其他題已驗證一律 302 轉登入頁）；連結以教務處專區頁的現場版本（2026-11-14）列出的為準，表單內容以快照為準。記錄見 sources/live/live_check.md 與登記表。",
        ],
    }
    out = HERE / "gold.json"
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已寫入 {out.relative_to(ROOT)}（{len(keypoints)} 個 keypoint，其中 {sum(1 for k in keypoints if k.get('registry'))} 個引用登記表）")
    print(f"引句驗證通過：{len(REFS)} 個 keypoint，{sum(len(v) for v in REFS.values())} 條")
    return 0


if __name__ == "__main__":
    sys.exit(main())
