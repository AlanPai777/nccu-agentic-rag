"""
Guard for the 2026-10-18 extractor change (rag/preprocess.py: base64 `script.e-enc` emails are decoded).
tiipm.nccu.edu.tw writes each address with JS; a plain HTTP fetch of its faculty page used to lose all 63 addresses.
Inline snippets only; no network, no LLM.
    python -W ignore -m unittest experiments.live_spikes.test_extractor_script_email -v
"""

from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import rag.preprocess as pp  # noqa: E402

EMAIL = "hychuang@g.nccu.edu.tw"
B64 = base64.b64encode(EMAIL.encode()).decode()
SCRIPT = ("<script class='e-enc%s'>(function () {var e = atob(\"" + B64 + "\");$('script.e-enc:not(.act)').eq(0)"
          ".before(\"<a href='mailto:\" + e + \"' title='\" + e + \"'>\" + e + \"</a>\").addClass('act');})();</script>")
URL = "https://tiipm.nccu.edu.tw/zh_tw/Faculty/members1"


def text(html: str) -> str:
    return pp.extract_html_bytes(html.encode(), URL)


class TestScriptEmail(unittest.TestCase):
    STATIC = "<html><body><main><p>電子郵件 : " + (SCRIPT % "") + "</p></main></body></html>"
    # what the browser leaves behind: the link the script wrote, then the same script marked `act`
    RENDERED = ("<html><body><main><p>電子郵件 : <a href='mailto:" + EMAIL + "'>" + EMAIL + "</a>" + (SCRIPT % " act") + "</p></main></body></html>")

    def test_static_page_gets_the_address(self):
        self.assertIn(f"[{EMAIL}](mailto:{EMAIL})", text(self.STATIC))

    def test_static_and_rendered_text_agree(self):
        self.assertEqual(text(self.STATIC), text(self.RENDERED))

    def test_rendered_page_is_not_doubled(self):
        self.assertEqual(text(self.RENDERED).count(EMAIL), 2)      # link text + mailto target, once

    def test_not_an_address_is_left_alone(self):
        bad = self.STATIC.replace(B64, base64.b64encode(b"no at sign").decode())
        self.assertNotIn("mailto", text(bad))


if __name__ == "__main__":
    unittest.main()
