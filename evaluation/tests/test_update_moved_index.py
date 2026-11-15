"""
scripts/update_moved_staff_pages_in_index.py 的測試（離線）：用假的索引、假的頁面與假的 moved_pages.json，不碰真正的 output/ 與 docs/。
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

import helpers

sys.path.insert(0, str(helpers.ROOT / "scripts"))
import update_moved_staff_pages_in_index as upd  # noqa: E402

HTML = ("<html><body><div class='item-page'><p>單位主管</p><p>姓名</p><p>劉桂芬</p><p>職稱</p><p>組長</p><p>校內分機</p><p>62120</p>"
        "<p>電子信箱</p><p>a@nccu.edu.tw</p><p>工作職掌</p><p>綜理督導業務、臨時交辦事項、各項臨櫃作業、款項收帳與票據管理、專戶管理與對帳作業</p></div></body></html>")
OLD = "https://cashier.nccu.edu.tw/PageStaffing?fid=7994"
NEW = "https://nccuga.nccu.edu.tw/zh/" + quote("人員職掌選單/出納組_")


def rec(name, url, text="舊文字", sub="x.nccu.edu.tw"):
    return {"category": "行政單位", "name": name, "url": url, "subdomain": sub, "text": text, "fetched_at": "2026-08-25T19:03:58"}


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        recs = [rec("甲", "https://a.nccu.edu.tw/"), rec("出納組", OLD, sub="cashier.nccu.edu.tw"), rec("乙", "https://b.nccu.edu.tw/")]
        self.index = self.d / "index.jsonl"
        self.index.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", encoding="utf-8")
        self.csv = self.d / "contact.csv"
        self.csv.write_text(f"行政單位,甲,https://a.nccu.edu.tw/\n行政單位,出納組,{OLD}\n行政單位,乙,https://b.nccu.edu.tw/\n", encoding="utf-8")
        self.moved = self.d / "moved.json"
        self.moved.write_text(json.dumps({"pages": [{"unit": "出納組", "old": OLD, "new": NEW}]}), encoding="utf-8")
        self.pages = self.d / "pages"
        self.pages.mkdir()
        (self.pages / "ga_cashier.rendered.html").write_text(HTML, encoding="utf-8")
        (self.pages / "ga_cashier.render.json").write_text(json.dumps({"url": NEW, "ok": True, "fetched_at": "2026-11-13T19:45:20+08:00"}), encoding="utf-8")

    def run_cli(self, *extra):
        return upd.main(["--index", str(self.index), "--csv", str(self.csv), "--moved", str(self.moved), "--pages-dir", str(self.pages), *extra])


class DryRunTest(Base):
    def test_preview_writes_nothing(self):
        before = (self.index.read_bytes(), self.csv.read_bytes())
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual((self.index.read_bytes(), self.csv.read_bytes()), before)


class ApplyTest(Base):
    def test_only_the_three_fields_of_that_line_change(self):
        before = [json.loads(x) for x in self.index.read_text(encoding="utf-8").splitlines()]
        raw_before = self.index.read_text(encoding="utf-8").splitlines()
        self.assertEqual(self.run_cli("--apply"), 0)
        raw_after = self.index.read_text(encoding="utf-8").splitlines()
        after = [json.loads(x) for x in raw_after]
        self.assertEqual((raw_after[0], raw_after[2]), (raw_before[0], raw_before[2]))     # 其他行逐字不動
        b, a = before[1], after[1]
        self.assertEqual(list(a), list(b))                                                  # 欄位順序不變
        self.assertEqual([k for k in a if a[k] != b[k]], ["url", "text", "fetched_at"])
        self.assertEqual((a["url"], a["fetched_at"], a["subdomain"], a["name"]), (NEW, "2026-11-13T19:45:20", "cashier.nccu.edu.tw", "出納組"))
        self.assertIn("劉桂芬", a["text"])
        self.assertTrue(self.index.read_text(encoding="utf-8").endswith("\n"))

    def test_csv_row_changes_and_format_is_kept(self):
        self.run_cli("--apply")
        self.assertEqual(self.csv.read_text(encoding="utf-8").splitlines(),
                         ["行政單位,甲,https://a.nccu.edu.tw/", f"行政單位,出納組,{NEW}", "行政單位,乙,https://b.nccu.edu.tw/"])

    def test_running_twice_changes_nothing_more(self):
        self.run_cli("--apply")
        once = (self.index.read_bytes(), self.csv.read_bytes())
        self.assertEqual(self.run_cli("--apply"), 0)
        self.assertEqual((self.index.read_bytes(), self.csv.read_bytes()), once)


class RefusalTest(Base):
    def assert_refused(self):
        before = (self.index.read_bytes(), self.csv.read_bytes())
        self.assertEqual(self.run_cli("--apply"), 2)
        self.assertEqual((self.index.read_bytes(), self.csv.read_bytes()), before)           # 出錯就什麼都不寫

    def test_old_url_missing(self):
        self.index.write_text(self.index.read_text(encoding="utf-8").replace(OLD, "https://zzz.nccu.edu.tw/"), encoding="utf-8")
        self.assert_refused()

    def test_old_url_twice(self):
        lines = self.index.read_text(encoding="utf-8").splitlines()
        self.index.write_text("\n".join(lines + [lines[1]]) + "\n", encoding="utf-8")
        self.assert_refused()

    def test_old_and_new_both_present(self):
        lines = self.index.read_text(encoding="utf-8").splitlines()
        self.index.write_text("\n".join(lines + [json.dumps(rec("出納組", NEW), ensure_ascii=False)]) + "\n", encoding="utf-8")
        self.assert_refused()

    def test_page_file_missing_or_not_ok(self):
        (self.pages / "ga_cashier.render.json").write_text(json.dumps({"url": NEW, "ok": False}), encoding="utf-8")
        self.assert_refused()

    def test_empty_extraction(self):
        (self.pages / "ga_cashier.rendered.html").write_text("<html><body></body></html>", encoding="utf-8")
        self.assert_refused()


class RealDataTest(unittest.TestCase):
    """真正的 moved_pages.json、索引、頁面檔：預演要能對 8 筆都找到對應（索引已更新後則全部是 already）。"""
    def test_every_moved_page_has_a_plan_without_errors(self):
        lines = upd.INDEX.read_text(encoding="utf-8").splitlines()
        plans = upd.make_plan(lines, upd.load_moved(), upd.load_pages())
        self.assertEqual(len(plans), 8)
        self.assertEqual([p for p in plans if p["action"] == "error"], [])


if __name__ == "__main__":
    unittest.main()
