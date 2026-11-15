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


class SiteNamesFromMovedPagesTest(unittest.TestCase):
    """site_names 的舊主機名稱由 moved_pages.json 推導，不再手寫（2026-11-15）。"""
    ROWS = [("總務處", "https://nccuga.nccu.edu.tw/"), ("甲組", "https://jia.nccu.edu.tw/p?x=1")]
    MOVED = [{"unit": "乙組", "old": "https://yi.nccu.edu.tw/PageStaffing?fid=1", "new": "https://nccuga.nccu.edu.tw/y"},
             {"unit": "丙組", "old": "https://jia.nccu.edu.tw/PageStaffing?fid=2", "new": "https://nccuga.nccu.edu.tw/b"},
             {"unit": "外部", "old": "https://example.com/x", "new": "https://nccuga.nccu.edu.tw/z"}]

    def names(self, moved, **kw):
        from rag.live import site_names as sn
        return sn.derive_names(self.ROWS, overrides={}, moved_pages=moved, **kw)

    def test_a_moved_pages_old_host_gets_the_units_name(self):
        n = self.names(self.MOVED)
        self.assertEqual(n["yi.nccu.edu.tw"], "乙組")
        self.assertNotIn("yi.nccu.edu.tw", self.names([]))                        # 沒有搬家紀錄就沒有這個名字

    def test_the_csv_wins_when_it_still_lists_the_host_and_foreign_hosts_are_ignored(self):
        n = self.names(self.MOVED)
        self.assertEqual(n["jia.nccu.edu.tw"], "甲組")                            # csv 還有這個主機：用 csv 的，不是「丙組」
        self.assertNotIn("example.com", n)

    def test_the_shipped_json_names_every_moved_pages_old_host(self):
        """不需要 docs/contact.csv（它沒有追蹤）：新增搬家頁卻忘了重新產生 site_names.json 時，這個測試會失敗。
        修法：python scripts/build_site_names.py（預演），再加 --write。"""
        shipped = json.loads((ROOT / "rag" / "live" / "site_names.json").read_text(encoding="utf-8"))
        for m in moved():
            host = urlparse(m["old"]).netloc
            self.assertEqual(shipped.get(host), m["unit"], f"{host}：site_names.json 沒有這個舊主機的名稱，請執行 scripts/build_site_names.py --write")

    def test_an_override_still_beats_everything(self):
        from rag.live import site_names as sn
        n = sn.derive_names(self.ROWS, overrides={"yi.nccu.edu.tw": "手寫"}, moved_pages=self.MOVED)
        self.assertEqual(n["yi.nccu.edu.tw"], "手寫")

    @unittest.skipUnless(CSV.exists(), "docs/contact.csv is not tracked and may be absent")
    def test_the_shipped_json_is_what_csv_moved_pages_and_overrides_give(self):
        from rag.live import site_names as sn
        shipped = json.loads((ROOT / "rag" / "live" / "site_names.json").read_text(encoding="utf-8"))
        self.assertEqual(sn.derive_names(sn.read_rows(CSV)), shipped)
        self.assertNotIn("dean.nccu.edu.tw", sn.OVERRIDES)                         # 不再手寫


@unittest.skipUnless(CSV.exists(), "docs/contact.csv is not tracked and may be absent")
class CsvTest(unittest.TestCase):
    def test_the_eight_rows_point_at_the_new_urls(self):
        lines = CSV.read_text(encoding="utf-8").splitlines()
        for m in moved():
            self.assertFalse([l for l in lines if l.endswith("," + m["old"])], m["unit"])
            self.assertEqual(len([l for l in lines if l.endswith("," + m["new"])]), 1, m["unit"])


if __name__ == "__main__":
    unittest.main()
