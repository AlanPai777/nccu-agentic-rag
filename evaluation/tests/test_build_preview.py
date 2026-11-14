"""evaluation/dashboard/build_preview.py：index.html → artifact 用的預覽檔（去掉外層標籤、內嵌資料）。"""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dashboard"))

import build_preview  # noqa: E402

SRC = (HERE.parent / "dashboard" / "index.html").read_text(encoding="utf-8")


class TestBuildPreview(unittest.TestCase):
    def test_full_document_has_an_empty_data_slot(self):
        self.assertIn(build_preview.EMPTY, SRC)
        self.assertTrue(SRC.lstrip().lower().startswith("<!doctype html>"))

    def test_fragment_drops_the_outer_tags_and_keeps_the_page(self):
        out = build_preview.build(SRC, '{"query": {"query_id": 1}}\n')
        for tag in ("<!doctype", "<html", "<head>", "</head>", "<body>", "</body>", "</html>", '<meta charset', 'name="viewport"'):
            self.assertNotIn(tag, out.lower(), tag)
        self.assertIn("<title>RAG Evaluation Dashboard</title>", out)
        self.assertIn("<style>", out)
        self.assertIn('id="drawer"', out)                           # 說明面板還在
        self.assertIn('name="claude:viewport-fit-sides"', out)

    def test_data_is_embedded_and_script_close_is_escaped(self):
        data = json.dumps({"query": {"query_id": 1, "content": "</script><b>"}}, ensure_ascii=False) + "\n"
        out = build_preview.build(SRC, data)
        self.assertIn('<script id="initial-data" type="text/plain">', out)
        self.assertNotIn("</script><b>", out)
        self.assertIn("<\\/script><b>", out)

    def test_missing_slot_raises(self):
        with self.assertRaises(ValueError):
            build_preview.build(SRC.replace(build_preview.EMPTY, ""), "{}")


if __name__ == "__main__":
    unittest.main()
