"""
Offline tests for P8 step S3: host -> user-facing site name, derived from docs/contact.csv (docs/phase_j_live_fetch_plan.md, P8.3 S3).
Reads local files only.   Run from the repo root:
    python -W ignore -m unittest experiments.live_spikes.test_live_s3_site_names -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rag.live import site_names as sn  # noqa: E402

CSV = ROOT / "docs" / "contact.csv"


class TestRules(unittest.TestCase):
    def names(self, rows, overrides=None):
        return sn.derive_names(rows, overrides={} if overrides is None else overrides)

    def test_root_row_beats_the_first_row(self):
        rows = [("教務長室", "https://aca.nccu.edu.tw/zh/a"), ("教務處", "https://aca.nccu.edu.tw")]
        self.assertEqual(self.names(rows), {"aca.nccu.edu.tw": "教務處"})
        self.assertEqual(self.names([("教務處", "https://aca.nccu.edu.tw/")]), {"aca.nccu.edu.tw": "教務處"})

    def test_a_root_url_with_a_query_is_not_the_root(self):
        rows = [("出納組", "https://cashier.nccu.edu.tw/PageStaffing?fid=1"), ("別的", "https://cashier.nccu.edu.tw/?x=1")]
        self.assertEqual(self.names(rows), {"cashier.nccu.edu.tw": "出納組"})

    def test_first_row_names_the_site_and_only_the_last_note_is_dropped(self):
        self.assertEqual(self.names([("商學院(現任院長)", "https://commerce.nccu.edu.tw/a")]), {"commerce.nccu.edu.tw": "商學院"})
        self.assertEqual(self.names([("企業管理研究所(MBA學位學程)(策略國際)", "https://mba.nccu.edu.tw/a")]),
                         {"mba.nccu.edu.tw": "企業管理研究所(MBA學位學程)"})
        self.assertEqual(self.names([("圖書館（各組聯絡資訊）", "https://www.lib.nccu.edu.tw/a")]), {"www.lib.nccu.edu.tw": "圖書館"})

    def test_a_name_that_is_only_a_note_is_not_emptied(self):
        self.assertEqual(sn.strip_note("(首頁)"), "(首頁)")

    def test_only_nccu_hosts_are_kept_and_the_host_is_lower_cased(self):
        rows = [("外部", "https://tigp.sinica.edu.tw/x"), ("別處", "https://web.alcd.center/y"), ("政大", "https://nccu.edu.tw/z"),
                ("系", "https://CS.nccu.edu.tw/a"), ("偽", "https://evilnccu.edu.tw/a")]
        self.assertEqual(self.names(rows), {"cs.nccu.edu.tw": "系", "nccu.edu.tw": "政大"})

    def test_overrides_win(self):
        rows = [("校長室", "https://www.nccu.edu.tw/p/1")]
        self.assertEqual(self.names(rows, {"www.nccu.edu.tw": "政大首頁", "moltke.nccu.edu.tw": "校務表單服務"}),
                         {"moltke.nccu.edu.tw": "校務表單服務", "www.nccu.edu.tw": "政大首頁"})

    def test_read_rows_takes_the_last_two_cells_and_skips_free_text(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.csv"
            p.write_text("行政單位,校長室,https://www.nccu.edu.tw/p/1\n林啓屏 副校長,https://www.nccu.edu.tw/p/2\n\n(以上完成)\n"
                         "行政單位,,https://x.nccu.edu.tw/y\n", encoding="utf-8")
            self.assertEqual(sn.read_rows(p), [("校長室", "https://www.nccu.edu.tw/p/1"), ("林啓屏 副校長", "https://www.nccu.edu.tw/p/2")])


class TestLookup(unittest.TestCase):
    def setUp(self):
        sn._table.cache_clear()
        self._p = mock.patch.object(sn, "_table", lambda: {"www.lib.nccu.edu.tw": "圖書館", "aca.nccu.edu.tw": "教務處"})
        self._p.start()

    def tearDown(self):
        self._p.stop()
        sn._table.cache_clear()

    def test_known_unknown_case_and_the_www_prefix(self):
        self.assertEqual(sn.site_name("aca.nccu.edu.tw"), "教務處")
        self.assertEqual(sn.site_name("ACA.nccu.edu.tw "), "教務處")
        self.assertEqual(sn.site_name("lib.nccu.edu.tw"), "圖書館")            # www. is optional
        self.assertEqual(sn.site_name("www.aca.nccu.edu.tw"), "教務處")
        self.assertEqual(sn.site_name("cd.nccu.edu.tw"), "cd.nccu.edu.tw")     # unknown: the host itself
        self.assertEqual(sn.site_name(""), "")


class TestTheShippedTable(unittest.TestCase):
    def test_the_json_is_what_the_csv_and_the_rules_give(self):
        if not CSV.exists():
            self.skipTest("docs/contact.csv not available")
        self.assertEqual(json.loads(sn.DATA.read_text(encoding="utf-8")), sn.derive_names(sn.read_rows(CSV)),
                         "site_names.json is stale: run experiments/live_spikes/build_site_names.py --write")

    def test_the_hosts_the_demo_shows(self):
        sn._table.cache_clear()
        want = {"aca.nccu.edu.tw": "教務處", "osa.nccu.edu.tw": "學生事務處", "cashier.nccu.edu.tw": "出納組", "www.lib.nccu.edu.tw": "圖書館",
                "oic.nccu.edu.tw": "國際合作事務處", "moltke.nccu.edu.tw": "校務表單服務", "www.nccu.edu.tw": "政大首頁",
                "www.cs.nccu.edu.tw": "資訊科學系", "www.es.nccu.edu.tw": "附設實驗國民小學", "es.video.nccu.edu.tw": "附設實驗國民小學（家長會）",
                "ahs.nccu.edu.tw": "附屬高級中學"}
        for host, name in want.items():
            self.assertEqual(sn.site_name(host), name, host)

    def test_no_two_hosts_share_a_name(self):
        table = json.loads(sn.DATA.read_text(encoding="utf-8"))
        names = list(table.values())
        self.assertEqual(len(names), len(set(names)), sorted({n for n in names if names.count(n) > 1}))

    def test_no_empty_names_and_no_host_outside_nccu(self):
        for host, name in json.loads(sn.DATA.read_text(encoding="utf-8")).items():
            self.assertTrue(name.strip(), host)
            self.assertTrue(host == "nccu.edu.tw" or host.endswith(".nccu.edu.tw"), host)


if __name__ == "__main__":
    unittest.main()
