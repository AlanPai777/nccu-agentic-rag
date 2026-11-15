"""
聯絡人索引裡 8 筆搬家的總務處人員頁（F19，2026-11-15 由 scripts/update_moved_staff_pages_in_index.py 改成新網址）的資料檢查。
離線：只讀 output/office_contacts_index.jsonl、rag/live/moved_pages.json、rag/live/site_names.json，不呼叫 LLM、不上網。
"""
import json
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import unquote, urlparse

import sys

import helpers

ROOT = helpers.ROOT
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
INDEX = ROOT / "output" / "office_contacts_index.jsonl"
MOVED = ROOT / "rag" / "live" / "moved_pages.json"
CSV = ROOT / "docs" / "contact.csv"


def moved():
    return json.loads(MOVED.read_text(encoding="utf-8"))["pages"]


def records():
    return [json.loads(l) for l in INDEX.read_text(encoding="utf-8").splitlines() if l.strip()]


class IndexTest(unittest.TestCase):
    def test_each_moved_page_is_in_the_index_once_at_the_new_url_and_not_at_the_old(self):
        recs = records()
        urls = [r["url"] for r in recs]
        for m in moved():
            self.assertEqual(urls.count(m["new"]), 1, m["unit"])
            self.assertEqual(urls.count(m["old"]), 0, m["unit"])

    def test_name_and_subdomain_are_kept_so_the_router_still_picks_the_corpus_folder(self):
        by_new = {r["url"]: r for r in records()}
        for m in moved():
            r = by_new[m["new"]]
            self.assertEqual(r["name"], m["unit"])
            self.assertEqual(r["subdomain"], urlparse(m["old"]).netloc)          # e.g. 出納組 stays cashier.nccu.edu.tw
            self.assertGreater(len(r["text"]), 500)
            self.assertTrue(r["fetched_at"].startswith("2026-11-13"))

    def test_the_index_still_has_one_record_per_contact_row(self):
        self.assertEqual(len(records()), 434)

    def test_the_cashier_contact_path_cites_the_new_url(self):
        from rag.skills import office_lookup_skill as skill
        new = next(m["new"] for m in moved() if m["unit"] == "出納組")
        with mock.patch.object(skill, "_llm_extract_contacts", lambda t: self.fail("the LLM must not be called")):
            e = skill.OfficeLookupSkill().run(["出納組"])["出納組"]
        self.assertEqual((e["contacts_source"], e["contact_urls"], e["page_url"]), ("page", [new], new))
        self.assertIn("劉桂芬", {c["name"] for c in e["contacts"]})
        self.assertIn(f"來源：{new}", skill.OfficeLookupSkill().format_context({"出納組": e}))

    def test_the_old_hosts_keep_their_names_in_the_sources_panel(self):
        table = json.loads((ROOT / "rag" / "live" / "site_names.json").read_text(encoding="utf-8"))
        for m in moved():
            self.assertEqual(table.get(urlparse(m["old"]).netloc), m["unit"])


@unittest.skipUnless(CSV.exists(), "docs/contact.csv is not tracked and may be absent")
class CsvTest(unittest.TestCase):
    def test_the_eight_rows_point_at_the_new_urls(self):
        lines = CSV.read_text(encoding="utf-8").splitlines()
        for m in moved():
            self.assertFalse([l for l in lines if l.endswith("," + m["old"])], m["unit"])
            self.assertEqual(len([l for l in lines if l.endswith("," + m["new"])]), 1, m["unit"])


if __name__ == "__main__":
    unittest.main()
