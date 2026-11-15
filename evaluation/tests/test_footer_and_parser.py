"""
頁尾抽取與聯絡人解析（2026-11-15）：離線，不呼叫 LLM（解析時的 LLM 一律換成「被呼叫就失敗」的假的），不上網。
用的是登記表裡 8 個總務處人員頁的現場渲染副本（evaluation/registry/sources/live/ga_*.rendered.html，2026-11-13）。
"""
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

import helpers

ROOT = helpers.ROOT
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LIVE = helpers.EVAL / "registry" / "sources" / "live"
PAGES = sorted(LIVE.glob("ga_*.rendered.html"))

from rag import preprocess as pp  # noqa: E402
from rag.skills import office_lookup_skill as sk  # noqa: E402


def no_llm():
    """解析時任何 LLM 呼叫都讓測試失敗。"""
    def boom(*a, **k):
        raise AssertionError("the LLM must not be called while parsing a staff page")
    return (mock.patch.object(sk, "_llm_extract_contacts", boom), mock.patch.object(sk, "simple_chat", boom))


def parse(text):
    a, b = no_llm()
    with a, b:
        return sk.parse_office_contacts(text)


def extract(path):
    return pp.extract_html_bytes(Path(path).read_bytes(), "https://x/y")


class FooterExtractionTest(unittest.TestCase):
    def test_the_contact_block_of_a_people_page_is_kept_once_after_the_mark(self):
        text = extract(LIVE / "ga_cashier.rendered.html")
        body, _, block = text.partition(pp.FOOTER_CONTACT_MARK)
        self.assertEqual(text.count(pp.FOOTER_CONTACT_MARK), 1)
        self.assertEqual(body.count("指南路二段64號 (行政大樓五樓)"), 1)             # 地址那一塊照舊，在標記之前
        for needle in ("(02)2939-3091", "出納組分機 62120", "傳真 (02)2939-4784"):
            self.assertEqual(block.count(needle), 1, needle)
            self.assertNotIn(needle, body)

    def test_the_icons_of_the_contact_block_become_words(self):
        """圖示抽成文字會不見：「傳真 (02)2939-4784 (02)2939-3091」讀起來兩個都是傳真（Q1 run04 把總機寫成傳真）。"""
        block = extract(LIVE / "ga_cashier.rendered.html").split(pp.FOOTER_CONTACT_MARK)[1]
        self.assertIn("信箱 nccuga@nccu.edu.tw", block)
        self.assertIn("傳真 (02)2939-4784", block)
        self.assertIn("電話 (02)2939-3091", block)
        self.assertNotIn("傳真 傳真", block)                                  # 項目本來就寫了「傳真」就不重複
        self.assertNotIn("電話 出納組分機", block)                              # 各組分機清單的圖示不加標籤，文字本來就寫了「XX分機」
        self.assertIn("出納組分機 62120", block)

    def test_an_icon_with_no_known_meaning_is_dropped_not_labelled(self):
        html = ("<html><body><div class='item-page'><p>" + "正文" * 60 + "</p></div><div class='jlcontactinfo-1'>"
                "<div class='tm-item'><span class='fas fa-star'></span> 專線 02-1</div></div></body></html>")
        text = pp.extract_html_bytes(html.encode("utf-8"), "https://x/y")
        self.assertIn("專線 02-1", text)
        self.assertNotIn("電話", text.split(pp.FOOTER_CONTACT_MARK)[1])

    def test_a_page_whose_only_footer_is_the_old_kind_does_not_change(self):
        html = ("<html><body><div class='item-page'><p>" + "正文" * 60 + "</p></div>"
                "<div class='jlfooterinfo-1'>116臺北市 行政大樓三樓</div></body></html>")
        text = pp.extract_html_bytes(html.encode("utf-8"), "https://x/y")
        self.assertIn("行政大樓三樓", text)
        self.assertNotIn(pp.FOOTER_CONTACT_MARK, text)

    def test_nested_contact_blocks_are_not_counted_twice(self):
        html = ("<html><body><div class='item-page'><p>" + "正文" * 60 + "</p></div>"
                "<div class='jlcontactinfo-1'><div class='jlcontactinfo-1-inner'>電話 02-1234 出納組分機 62120</div></div></body></html>")
        text = pp.extract_html_bytes(html.encode("utf-8"), "https://x/y")
        self.assertEqual(text.count("出納組分機 62120"), 1)

    def test_a_footer_tag_without_a_known_block_is_still_dropped(self):
        html = "<html><body><div class='item-page'><p>" + "內容" * 60 + "</p></div><footer><p>版權所有</p></footer></body></html>"
        text = pp.extract_html_bytes(html.encode("utf-8"), "https://x/y")
        self.assertNotIn("版權所有", text)


class CompareAndParserIgnoreTheBlockTest(unittest.TestCase):
    def test_a_contact_block_on_one_side_only_is_not_a_changed_page(self):
        from rag.live.compare import compare
        full = extract(LIVE / "ga_cashier.rendered.html")
        body = full.split(pp.FOOTER_CONTACT_MARK)[0]
        self.assertTrue(compare(body, full).same)
        self.assertTrue(compare(full, body).same)
        self.assertFalse(compare(body, body.replace("62120", "62999")).same)      # 頁面本身真的變了還是會抓到

    def test_the_flattened_table_tier_is_not_disabled_by_the_block(self):
        """aca 註冊組的人員頁是攤平的表格；「分機」只出現幾次是第二層解析判斷它的依據。頁尾區塊的許多「分機」不能讓它失效。"""
        text = (helpers.EVAL / "registry" / "sources" / "snapshot" / "aca_staff_registrar.txt").read_text(encoding="utf-8")
        block = pp.FOOTER_CONTACT_MARK + "\n教務處 電話 02-1234 傳真 02-5678 註冊組分機 63273 課務組分機 63277 綜合業務組分機 63281 教務長室分機 63270"
        base = {(c["name"], c["ext"]) for c in parse(text)}
        self.assertGreater(len(base), 3)
        self.assertEqual({(c["name"], c["ext"]) for c in parse(text + "\n\n" + block)}, base)


class ParserOnTheEightPagesTest(unittest.TestCase):
    def test_the_contact_block_changes_nobody_on_any_page_and_needs_no_llm(self):
        self.assertEqual(len(PAGES), 8)
        for path in PAGES:
            full = extract(path)
            body = full.split(pp.FOOTER_CONTACT_MARK)[0]
            self.assertLess(len(body), len(full), path.name)          # 區塊真的在
            self.assertEqual({(c["name"], c["ext"]) for c in parse(full)}, {(c["name"], c["ext"]) for c in parse(body)}, path.name)

    def test_no_footer_extension_becomes_a_person(self):
        footer_exts = {"62093", "62875", "62108", "62090", "62806", "62820", "63354", "63353"}
        for path in PAGES:
            full = extract(path)
            body = full.split(pp.FOOTER_CONTACT_MARK)[0]
            for c in parse(full):
                if c["ext"] in footer_exts:      # 頁尾列的分機，只有在頁面本文也有那張卡時才可能是人
                    self.assertIn(c["ext"], body, path.name)

    def test_the_nurse_after_two_vacant_cards_is_read(self):
        people = {(c["name"], c["ext"]) for c in parse(extract(LIVE / "ga_safety.rendered.html"))}
        self.assertIn(("潘宥芯", "62897"), people)

    def test_cashier_has_its_ten_people(self):
        people = {(c["name"], c["ext"]) for c in parse(extract(LIVE / "ga_cashier.rendered.html"))}
        self.assertEqual(len(people), 10)
        self.assertIn(("劉桂芬", "62120"), people)
        self.assertIn(("余淑娟", "62123"), people)
        self.assertNotIn("62173", {e for _, e in people})                 # 現場是「待補」，不是人


class UnitLinesPromptTest(unittest.TestCase):
    def test_the_mark_is_not_sent_to_the_llm_but_the_block_is(self):
        sent = []

        def fake_chat(messages, **kw):
            sent.append(messages[0]["content"])
            return "[]"
        full = extract(LIVE / "ga_cashier.rendered.html")
        self.assertIn(pp.FOOTER_CONTACT_MARK, full)
        sk._unit_contacts_cache.clear()
        with mock.patch.object(sk, "simple_chat", fake_chat):
            sk.llm_unit_contacts(full)
        self.assertEqual(len(sent), 1)
        self.assertNotIn(pp.FOOTER_CONTACT_MARK, sent[0])
        for needle in ("電話 (02)2939-3091", "傳真 (02)2939-4784", "出納組分機 62120"):
            self.assertIn(needle, sent[0])
        sk._unit_contacts_cache.clear()


class ParserRulesTest(unittest.TestCase):
    CARD = "姓名\n\n{n}\n\n職稱\n\n{t}\n\n校內分機\n\n{e}\n\n電子信箱\n\n[x@nccu.edu.tw](mailto:x@nccu.edu.tw)\n\n工作職掌\n\n1.業務\n\n"

    def test_the_label_nearest_the_extension_is_the_cards_own(self):
        text = (self.CARD.format(n="待補", t="組員", e="—") * 2) + self.CARD.format(n="王小明", t="組員", e="62001")
        self.assertEqual([(c["name"], c["ext"]) for c in parse(text)], [("王小明", "62001")])

    def test_a_placeholder_card_with_a_number_is_still_not_a_person(self):
        contacts, _ = sk._parse_labeled(self.CARD.format(n="待補", t="組員", e="62002"))      # (整頁一個人都沒有時，parse_office_contacts 還有別的備援層，這裡只測標籤層)
        self.assertEqual(contacts, [])

    def test_a_footer_unit_line_is_not_a_person_even_after_a_card_with_no_number(self):
        text = (self.CARD.format(n="王小明", t="組員", e="62001") + self.CARD.format(n="李小華", t="助理", e="—")
                + "116臺北市文山區指南路二段64號 總務長室分機 62093 出納組分機 62120")
        self.assertEqual([(c["name"], c["ext"]) for c in parse(text)], [("王小明", "62001")])

    def test_the_unit_extension_test(self):
        def m(s):
            return sk._EXT_LABELED_RE.search(s)
        for s, expect in (("出納組分機 62120", True), ("總務長室分機 62093", True), ("組長\n校內分機 62120", False),
                          ("組長校內分機 62120", False), ("電話：分機 62120", False), ("(02)2939-3091分機62120", False)):
            self.assertEqual(sk._is_unit_extension(s, m(s)), expect, s)


if __name__ == "__main__":
    unittest.main()
