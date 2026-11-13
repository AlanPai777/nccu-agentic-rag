"""
通用的 gold 檢查：掃 evaluation/*/gold.json（每新增一題，它的 gold 自動被檢查，不必每題各寫一份）。
檢查邏輯在 evaluation/gold_check.py（build-eval-gold skill 的驗證腳本共用同一份）；這裡再用「故意弄壞的 gold」
確認檢查真的抓得到問題，免得檢查本身壞了卻一直顯示通過。
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
from gold_check import validate_gold

GOLDS = sorted(helpers.EVAL.glob("*/gold.json"))


class GoldFilesTest(unittest.TestCase):
    def test_at_least_one_gold_is_found(self):
        self.assertTrue(GOLDS, "evaluation/*/gold.json 一個都找不到")

    def test_every_gold_passes(self):
        for path in GOLDS:
            with self.subTest(gold=path.parent.name):
                self.assertEqual(validate_gold(path), [])


class LivePdfTextIsReadTest(unittest.TestCase):
    """現場 PDF 轉出的 <檔名>.pdf.txt 也算來源原文（course_limit 的現場依據是 PDF）；檔案不在就驗證不過。"""

    def minimal_gold(self, quote):
        return {"query_id": "x", "query": "q", "content": "c", "data_as_of": {},
                "keypoints": [{"id": "K1", "text": "t", "kind": "hard",
                               "references": [{"text": quote, "source_url": "u", "source_kind": "live", "as_of": "d"}]}]}

    def test_a_quote_found_only_in_a_live_pdf_text(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        live = d / "sources" / "live"
        live.mkdir(parents=True)
        (live / "doc.pdf.txt").write_text("學士班學生每學期上限\n為25學分", encoding="utf-8")
        (d / "gold.json").write_text(json.dumps(self.minimal_gold("每學期上限為25學分"), ensure_ascii=False), encoding="utf-8")
        self.assertEqual(validate_gold(d / "gold.json"), [])
        (live / "doc.pdf.txt").unlink()
        (live / "other.pdf.txt").write_text("完全不相干的內容", encoding="utf-8")
        self.assertTrue(any("引文不在來源原文裡" in p for p in validate_gold(d / "gold.json")))


class LiveHtmlLinksAreReadTest(unittest.TestCase):
    """現場 HTML 裡只出現在 href 屬性的網址（表單連結），要能被引句驗證到：連結寫成 [文字](網址)，與快照的 markdown 連結同形。"""

    def gold(self, quote):
        return {"query_id": "x", "query": "q", "content": "c", "data_as_of": {},
                "keypoints": [{"id": "K1", "text": "t", "kind": "hard",
                               "references": [{"text": quote, "source_url": "u", "source_kind": "live", "as_of": "d"}]}]}

    def check(self, html_text, quote):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        live = d / "sources" / "live"
        live.mkdir(parents=True)
        (live / "page.html").write_text(html_text, encoding="utf-8")
        (d / "gold.json").write_text(json.dumps(self.gold(quote), ensure_ascii=False), encoding="utf-8")
        return validate_gold(d / "gold.json")

    def test_the_url_in_an_href_can_be_quoted(self):
        page = '<p><span><a style="x" href="https://moltke.nccu.edu.tw/f?viewdetail=QP-1&amp;x=2">休學/保留學籍\n<b>申請書</b></a></span></p>'
        self.assertEqual(self.check(page, "[休學/保留學籍申請書](https://moltke.nccu.edu.tw/f?viewdetail=QP-1&x=2)"), [])

    def test_a_url_that_is_not_in_any_href_is_not_found(self):
        page = '<a href="https://moltke.nccu.edu.tw/f?viewdetail=QP-1">休學申請書</a>'
        self.assertTrue(any("引文不在來源原文裡" in p for p in self.check(page, "[休學申請書](https://moltke.nccu.edu.tw/f?viewdetail=QP-2)")))

    def test_plain_text_around_links_is_still_found(self):
        page = '<p>本校學士班學生每學期上限為25學分，<a href="https://x.example/a">詳見</a>學則。</p>'
        self.assertEqual(self.check(page, "本校學士班學生每學期上限為25學分"), [])


class GoldCheckCatchesProblemsTest(unittest.TestCase):
    """複製出納組的 gold 與來源到暫存資料夾，各弄壞一處，確認 validate_gold 抓得到。"""

    def broken(self, edit):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        shutil.copytree(helpers.GOLD.parent / "sources", d / "sources")
        gold = helpers.read(helpers.GOLD)
        edit(gold)
        (d / "gold.json").write_text(json.dumps(gold, ensure_ascii=False), encoding="utf-8")
        return validate_gold(d / "gold.json")

    def test_the_untouched_copy_passes(self):
        self.assertEqual(self.broken(lambda g: None), [])

    def test_a_reference_that_is_not_in_the_sources(self):
        def edit(g):
            g["keypoints"][0]["references"][0]["text"] = "出納組分機 99999（編造的引文）"
        self.assertTrue(any("引文不在來源原文裡" in p for p in self.broken(edit)))

    def test_duplicate_keypoint_ids(self):
        def edit(g):
            g["keypoints"][1]["id"] = "K1"
        self.assertTrue(any("編號重複" in p for p in self.broken(edit)))

    def test_a_keypoint_without_references(self):
        def edit(g):
            g["keypoints"][0]["references"] = []
        self.assertTrue(any("沒有任何 reference" in p for p in self.broken(edit)))

    def test_an_acceptable_extension_outside_the_allowed_set(self):
        def edit(g):
            g["keypoints"][1]["acceptable_expressions"].append("99999")
        self.assertTrue(any("不在 allowed_values" in p for p in self.broken(edit)))

    def test_a_disallowed_value_that_is_also_allowed(self):
        def edit(g):
            g["allowed_values"]["disallowed"][0]["value"] = "62120"
        self.assertTrue(any("同時在允許集合" in p for p in self.broken(edit)))

    def test_a_conditional_keypoint_without_value_check(self):
        def edit(g):
            del g["keypoints"][2]["value_check"]
        self.assertTrue(any("條件式 keypoint" in p for p in self.broken(edit)))

    def test_a_person_quote_that_is_not_in_the_sources(self):
        def edit(g):
            g["allowed_values"]["extension_by_person"][0]["quote"] = "沒有這個人 校內分機 00000"
        self.assertTrue(any("人員頁引句不在來源原文裡" in p for p in self.broken(edit)))


if __name__ == "__main__":
    unittest.main()
