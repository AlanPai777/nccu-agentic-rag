"""
Guard for the 2026-10-16 extractor change (rag/preprocess.py: `header` is no longer a noise class-name token).
Recorded pages only (P0 fixtures); no network, no LLM.
    python -W ignore -m unittest experiments.live_spikes.test_extractor_header -v
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import rag.preprocess as pp  # noqa: E402
import rag.skills.office_lookup_skill as skill  # noqa: E402

FIX = ROOT / "experiments" / "live_fixtures" / "chain_xiuxue_2026-10-14"
# the rule as it was before the change
OLD_RULE = re.compile(r"(?:^|[-_])(?:nav|menu|breadcrumb|sidebar|footer|header)(?:$|[-_])", re.I)
OIC = "19_office_國際合作事務處.html"
OTHERS = ["11_office_註冊組.html", "12_office_教務長室.html", "13_office_住宿輔導組.html", "14_office_生活事務暨僑生輔導組.html",
          "15_office_原住民族學生資源中心.html", "16_office_身心健康中心.html", "17_office_出納組.html",
          "18_office_圖書館_各組聯絡資訊.html", "01_aca_xiuxue.html"]


def extract(raw: bytes, old: bool) -> str:
    if old:
        with mock.patch.object(pp, "_NOISE_CLASS_RE", OLD_RULE):
            return pp.extract_html_bytes(raw, "https://x.nccu.edu.tw/p")
    return pp.extract_html_bytes(raw, "https://x.nccu.edu.tw/p")


class TestRule(unittest.TestCase):
    HTML = ("<html><body><header>SITE BANNER</header><nav>NAV TAG</nav>"
            "<div class='site-menu'>MENU CLASS</div><div class='breadcrumb'>CRUMBS</div><div class='sidebar'>SIDE</div>"
            "<div class='footer-x'>FOOT</div>"
            "<div class='staff-header-row'><span>陳美芬</span> <span>國合長</span></div><p>分機：67102</p></body></html>")

    def test_the_card_header_survives_and_real_chrome_is_still_removed(self):
        t = pp.extract_html_bytes(self.HTML.encode(), "https://x.nccu.edu.tw/p")
        self.assertIn("陳美芬", t)
        for noise in ("SITE BANNER", "NAV TAG", "MENU CLASS", "CRUMBS", "SIDE", "FOOT"):
            self.assertNotIn(noise, t, noise)

    def test_the_old_rule_deleted_the_name(self):
        self.assertNotIn("陳美芬", extract(self.HTML.encode(), old=True))


@unittest.skipUnless(FIX.exists(), "fixtures not present")
class TestRecordedPages(unittest.TestCase):
    def test_oic_now_has_the_names_the_old_rule_deleted(self):
        raw = (FIX / OIC).read_bytes()
        old, new = extract(raw, True), extract(raw, False)
        self.assertNotIn("陳美芬", old)
        self.assertIn("陳美芬 國合長", new)
        self.assertIn("蘇卓馨 副國合長", new)
        self.assertGreater(len(new), len(old))
        old_lines = [l for l in old.splitlines() if l.strip()]
        new_text = new
        self.assertTrue(all(l in new_text for l in old_lines), "the new text must be a superset of the old")

    def test_the_other_nine_recorded_pages_are_byte_for_byte_unchanged(self):
        for n in OTHERS:
            with self.subTest(n):
                raw = (FIX / n).read_bytes()
                self.assertEqual(extract(raw, True), extract(raw, False))

    def test_the_staff_page_parser_is_untouched_for_the_eight_pages_that_did_not_change(self):
        # same extracted text -> same parse; asserted through the text equality above, spot-checked on the parse itself
        with mock.patch.object(skill, "_llm_extract_contacts", lambda t: []):
            for n in ("12_office_教務長室.html", "11_office_註冊組.html"):
                raw = (FIX / n).read_bytes()
                self.assertEqual(skill.parse_office_contacts(extract(raw, True)), skill.parse_office_contacts(extract(raw, False)))

    def test_oic_is_now_handed_to_the_llm_reader_with_the_names_in_it(self):
        """Before: the parser found no names, so the LLM was never asked and the answer used KNOWN_CONTACTS. Now it finds
        candidates (some of them garbled guesses), which is the situation the parser already hands to the LLM."""
        raw = (FIX / OIC).read_bytes()
        seen: list[str] = []
        with mock.patch.object(skill, "_llm_extract_contacts", lambda t: seen.append(t) or []):
            skill.parse_office_contacts(extract(raw, True))
            self.assertEqual(seen, [])                                  # old text: LLM never consulted
            skill.parse_office_contacts(extract(raw, False))
        self.assertEqual(len(seen), 1)
        self.assertIn("陳美芬 國合長", seen[0])                           # and what it reads now contains the names


if __name__ == "__main__":
    unittest.main(verbosity=2)
