"""
stage3 的 check_trace：驗證判斷者寫的 trace.json（純函式，不讀寫檔案）。
  - answer_span 必須是答案正文的子字串；evidence quote 必須是證據項目的子字串（空白正規化）
  - 引文不實的主張，標 supported 也會降為 unsupported
  - 主張的片段被另一個主張包含，不重複計入（以較長的為準）；只部分重疊的警告、兩者都計入
"""
import unittest

import helpers  # noqa: F401  （設定 sys.path 與環境變數）
from stage3 import check_trace

ANSWER = "電話： (02) 2939-3091 分機 62120\n劉桂芬（組長）分機 62123"
EVIDENCE = "☎ 總務處出納組：電話 (02)2939-3091 分機 62120\n• 劉桂芬（組長）分機 62120  vicky928@nccu.edu.tw"
TI = {"answer_text": ANSWER, "evidence_items": [{"id": "E1", "kind": "contact_list", "text": EVIDENCE}]}


def claim(cid, span, status="supported", quote=None):
    return {"id": cid, "answer_span": span, "status": status,
            "evidence": [{"item": "E1", "quote": quote}] if quote else []}


def by_id(out):
    return {c["id"]: c for c in out["claims"]}


class CheckTraceTest(unittest.TestCase):
    def test_a_good_claim_is_verified_and_counted(self):
        out = check_trace(TI, {"claims": [claim("c1", "(02) 2939-3091", quote="電話 (02)2939-3091 分機 62120")]})
        c = by_id(out)["c1"]
        self.assertTrue(c["span_verified"])
        self.assertTrue(c["evidence"][0]["verified"])
        self.assertEqual(c["status_checked"], "supported")
        self.assertTrue(c["counted"])
        self.assertEqual(out["warnings"], [])

    def test_a_span_that_is_not_in_the_answer_is_not_verified(self):
        out = check_trace(TI, {"claims": [claim("c1", "行政大樓 9 樓", quote="電話 (02)2939-3091")]})
        self.assertFalse(by_id(out)["c1"]["span_verified"])
        self.assertTrue(any("answer_span 不在答案正文" in w for w in out["warnings"]))

    def test_a_made_up_quote_downgrades_a_supported_claim(self):
        out = check_trace(TI, {"claims": [claim("c1", "(02) 2939-3091", quote="傳真 (02)0000-0000")]})
        c = by_id(out)["c1"]
        self.assertFalse(c["evidence"][0]["verified"])
        self.assertEqual(c["status"], "supported")                 # 判斷者寫的不改
        self.assertEqual(c["status_checked"], "unsupported")       # 檢查後降級
        self.assertTrue(any("降為 unsupported" in w for w in out["warnings"]))

    def test_a_supported_claim_without_any_evidence_is_downgraded(self):
        out = check_trace(TI, {"claims": [claim("c1", "分機 62120")]})
        self.assertEqual(by_id(out)["c1"]["status_checked"], "unsupported")

    def test_quote_matching_ignores_whitespace_and_fullwidth_spaces(self):
        ti = {"answer_text": "行政大樓 5 樓", "evidence_items": [{"id": "E1", "text": "出納組　行政大樓 5 樓　分機 62123"}]}
        out = check_trace(ti, {"claims": [claim("c1", "行政大樓 5 樓", quote="出納組 行政大樓5樓 分機62123")]})
        self.assertTrue(by_id(out)["c1"]["evidence"][0]["verified"])

    def test_a_claim_contained_in_a_longer_one_is_not_counted_twice(self):
        out = check_trace(TI, {"claims": [claim("c1", "劉桂芬（組長）", quote="劉桂芬（組長）"),
                                          claim("c2", "劉桂芬（組長）分機 62123", "unsupported")]})
        c = by_id(out)
        self.assertFalse(c["c1"]["counted"])
        self.assertEqual(c["c1"]["contained_in"], "c2")
        self.assertTrue(c["c2"]["counted"])
        self.assertTrue(any("c1 的片段被 c2 包含" in w for w in out["warnings"]))

    def test_the_longer_claim_listed_first_still_wins(self):
        out = check_trace(TI, {"claims": [claim("c1", "劉桂芬（組長）分機 62123", "unsupported"),
                                          claim("c2", "劉桂芬（組長）", quote="劉桂芬（組長）")]})
        c = by_id(out)
        self.assertTrue(c["c1"]["counted"])
        self.assertFalse(c["c2"]["counted"])

    def test_the_same_words_on_two_different_lines_are_not_an_overlap(self):
        ti = {"answer_text": "電話 分機 62120\n劉桂芬 分機 62120", "evidence_items": [{"id": "E1", "text": "分機 62120"}]}
        out = check_trace(ti, {"claims": [claim("c1", "分機 62120", quote="分機 62120"),
                                          claim("c2", "劉桂芬 分機 62120", quote="分機 62120")]})
        c = by_id(out)
        self.assertTrue(c["c1"]["counted"] and c["c2"]["counted"])
        self.assertEqual(out["warnings"], [])
        self.assertLess(c["c1"]["span_pos"][1], c["c2"]["span_pos"][0])    # c1 取第一行的位置

    def test_a_partial_overlap_warns_and_counts_both(self):
        ti = {"answer_text": "ABCDEFG", "evidence_items": [{"id": "E1", "text": "x"}]}
        out = check_trace(ti, {"claims": [claim("c1", "ABCDE", "unsupported"), claim("c2", "CDEFG", "unsupported")]})
        c = by_id(out)
        self.assertTrue(c["c1"]["counted"] and c["c2"]["counted"])
        self.assertTrue(any("部分重疊" in w for w in out["warnings"]))


if __name__ == "__main__":
    unittest.main()


URL = "https://moltke.example/formservice_SSO/link.jsp?viewdetail=QP-T01-03-02"
TI_URL = {"answer_text": "下載連結：" + URL + "\n負責退費業務",
          "evidence_items": [{"id": "E1", "kind": "HumanMessage", "text": "get_form 取得表單 休學/保留學籍申請書\n\n全文：\n表單編號：QP-T01-03-02",
                              "sources": [{"url": URL, "label": "休學/保留學籍申請書"},
                                          {"url": "https://osa.example/休退學退費/休-退-學退費標準", "label": "補充來源（樓層、電話）"}]}]}


def url_claim(cid, span, quote, **kw):
    return {"id": cid, "answer_span": span, "status": "supported",
            "evidence": [dict({"item": "E1", "quote": quote, "from": "sources"}, **kw)]}


class UrlClaimTest(unittest.TestCase):
    """網址主張可以引用證據項目的 sources，但 quote 必須等於其中一個完整網址（不是子字串）。"""

    def test_a_whole_source_url_is_a_valid_quote_and_its_label_is_kept(self):
        out = check_trace(TI_URL, {"claims": [url_claim("c1", "下載連結：" + URL, URL)]})
        c = by_id(out)["c1"]
        e = c["evidence"][0]
        self.assertTrue(e["verified"])
        self.assertEqual((e["quote_in"], e["label"]), ("sources", "休學/保留學籍申請書"))
        self.assertEqual(c["status_checked"], "supported")
        self.assertEqual(out["warnings"], [])

    def test_a_made_up_url_that_differs_by_one_character_is_not_valid(self):
        out = check_trace(TI_URL, {"claims": [url_claim("c1", "下載連結：" + URL, URL.replace("QP-T01-03-02", "QP-T01-03-09"))]})
        c = by_id(out)["c1"]
        self.assertFalse(c["evidence"][0]["verified"])
        self.assertEqual(c["status_checked"], "unsupported")           # 標了 supported 也降級
        self.assertTrue(any("完整網址" in w for w in out["warnings"]))

    def test_words_taken_from_the_path_cannot_support_another_claim(self):
        # T5 的陷阱：網址路徑裡有「退費」，不能拿「退費」去支持「負責退費業務」
        out = check_trace(TI_URL, {"claims": [url_claim("c1", "負責退費業務", "退費")]})
        c = by_id(out)["c1"]
        self.assertFalse(c["evidence"][0]["verified"])
        self.assertEqual(c["status_checked"], "unsupported")

    def test_a_part_of_a_url_is_not_a_whole_url(self):
        out = check_trace(TI_URL, {"claims": [url_claim("c1", "下載連結：" + URL, "https://moltke.example/formservice_SSO")]})
        self.assertFalse(by_id(out)["c1"]["evidence"][0]["verified"])

    def test_the_spelling_of_the_url_is_normalised(self):
        encoded = "HTTPS://MOLTKE.example/formservice_SSO/link.jsp?viewdetail=QP-T01-03-02/"
        out = check_trace(TI_URL, {"claims": [url_claim("c1", "下載連結：" + URL, encoded)]})
        self.assertTrue(by_id(out)["c1"]["evidence"][0]["verified"])
        osa = "https://osa.example/%E4%BC%91%E9%80%80%E5%AD%B8%E9%80%80%E8%B2%BB/%E4%BC%91-%E9%80%80-%E5%AD%B8%E9%80%80%E8%B2%BB%E6%A8%99%E6%BA%96"
        out = check_trace(TI_URL, {"claims": [url_claim("c1", "負責退費業務", osa)]})
        self.assertTrue(by_id(out)["c1"]["evidence"][0]["verified"])      # 百分比編碼與原字相同

    def test_an_unknown_from_value_is_not_valid_and_an_item_without_sources_does_not_crash(self):
        out = check_trace(TI_URL, {"claims": [url_claim("c1", "下載連結：" + URL, URL, **{"from": "header"})]})
        self.assertFalse(by_id(out)["c1"]["evidence"][0]["verified"])
        self.assertTrue(any("from 只能是 sources" in w for w in out["warnings"]))
        old = {"answer_text": "x", "evidence_items": [{"id": "E1", "kind": "k", "text": "t"}]}        # 舊的 trace_input：沒有 sources 欄位
        out = check_trace(old, {"claims": [url_claim("c1", "x", URL)]})
        self.assertFalse(by_id(out)["c1"]["evidence"][0]["verified"])

    def test_a_normal_text_quote_is_unchanged(self):
        out = check_trace(TI_URL, {"claims": [{"id": "c1", "answer_span": "下載連結", "status": "supported",
                                               "evidence": [{"item": "E1", "quote": "表單編號：QP-T01-03-02"}]}]})
        e = by_id(out)["c1"]["evidence"][0]
        self.assertTrue(e["verified"])
        self.assertNotIn("quote_in", e)
