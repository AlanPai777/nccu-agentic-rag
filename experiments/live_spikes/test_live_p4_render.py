"""
Tests for the real single-page rendering (P4 step 2): PlaywrightBackend.render + rag/live/extract.py.
Real Chromium, but ONLY against a throw-away HTTP server on 127.0.0.1 (the URL allowlist is swapped for one that accepts
localhost, and sub-resource requests to other hosts are aborted). Nothing is sent to nccu.edu.tw, no LLM.
    python -W ignore -m unittest experiments.live_spikes.test_live_p4_render -v
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rag.live.browser import BrowserOwner, PlaywrightBackend  # noqa: E402
from rag.live.compare import compare  # noqa: E402
from rag.live.extract import html_to_text  # noqa: E402

FIX = ROOT / "experiments" / "live_fixtures" / "chain_xiuxue_2026-10-14"
PAGE = "<html><body><div class='item-page'><p>{}</p></div></body></html>"


class Handler(BaseHTTPRequestHandler):
    fixtures: dict[str, bytes] = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path == "/static":
            self._send(200, PAGE.format("靜態內容 62160").encode())
        elif path == "/js":      # content arrives 300 ms after load -- the reason for the settle wait
            self._send(200, ("<html><body><div class='item-page' id='c'><p>載入中</p></div><script>"
                             "setTimeout(function(){document.getElementById('c').innerHTML='<p>延遲載入 63273</p>'},300)"
                             "</script></body></html>").encode())
        elif path == "/big5":     # declares big5 although the DOM is Unicode: the extractor must not trust that
            self._send(200, ("<html><head><meta charset='big5'></head><body><div class='item-page'><p>休學申請</p></div></body></html>"
                             ).encode("utf-8"), ctype="text/html; charset=utf-8")
        elif path == "/redirect":
            self._send(302, headers=[("Location", "/static")])
        elif path == "/to-forbidden":
            self._send(302, headers=[("Location", "/forbidden")])
        elif path == "/forbidden":
            self._send(200, PAGE.format("不該被抓到").encode())
        elif path == "/missing":
            self._send(404, b"nope")
        elif path == "/boom":
            self._send(500, b"oops")
        elif path == "/slow":
            time.sleep(3)
            self._send(200, PAGE.format("太慢了").encode())
        elif path == "/cf":
            self._send(200, b"<html><head><script>window._cf_chl_opt={}</script></head><body>Just a moment...</body></html>")
        elif path == "/setcookie":
            self._send(200, PAGE.format("cookie set").encode(), headers=[("Set-Cookie", "sid=abc; Path=/")])
        elif path == "/echocookie":
            self._send(200, PAGE.format("cookie=" + self.headers.get("Cookie", "NONE")).encode())
        elif path.startswith("/fx/") and path[4:] in Handler.fixtures:
            self._send(200, Handler.fixtures[path[4:]])
        else:
            self._send(404, b"?")


def allow_local(url: str) -> bool:
    p = urlsplit(url)
    return p.scheme == "http" and p.hostname == "127.0.0.1" and not p.path.startswith("/forbidden")


def only_local(url: str) -> bool:
    return url.startswith("data:") or urlsplit(url).hostname == "127.0.0.1"


class RenderBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.owner = BrowserOwner(lambda: PlaywrightBackend(settle_ms=800, nav_timeout_ms=10_000, allow=allow_local,
                                                           subresource_allow=only_local), idle_seconds=300)

    @classmethod
    def tearDownClass(cls):
        cls.owner.shutdown()
        cls.srv.shutdown()

    def render(self, path: str):
        return self.owner.render(self.base + path).result(60)


class TestRender(RenderBase):
    def test_static_page(self):
        r = self.render("/static")
        self.assertTrue(r.ok, r.detail)
        self.assertEqual(r.status, 200)
        text, err = html_to_text(r.html, r.url)
        self.assertEqual(err, "")
        self.assertIn("靜態內容 62160", text)

    def test_late_js_content_is_captured_after_the_settle_wait(self):
        r = self.render("/js")
        self.assertIn("延遲載入 63273", html_to_text(r.html, r.url)[0])

    def test_without_the_settle_wait_the_late_content_is_missed(self):
        o = BrowserOwner(lambda: PlaywrightBackend(settle_ms=0, nav_timeout_ms=10_000, allow=allow_local,
                                                   subresource_allow=only_local))
        try:
            r = o.render(self.base + "/js").result(60)
        finally:
            o.shutdown()
        self.assertNotIn("延遲載入 63273", html_to_text(r.html, r.url)[0])   # proves the 2 s wait is doing real work

    def test_chinese_survives_even_when_the_page_declares_a_wrong_charset(self):
        r = self.render("/big5")
        self.assertIn("休學申請", html_to_text(r.html, r.url)[0])

    def test_redirect_is_followed(self):
        r = self.render("/redirect")
        self.assertTrue(r.ok)
        self.assertIn("靜態內容", html_to_text(r.html, r.url)[0])

    def test_redirect_to_a_disallowed_place_is_refused(self):
        r = self.render("/to-forbidden")
        self.assertEqual((r.ok, r.error), (False, "redirect_offsite"))
        self.assertEqual(r.html, b"")

    def test_http_errors(self):
        a, b = self.render("/missing"), self.render("/boom")
        self.assertEqual((a.ok, a.error, a.status), (False, "http_4xx", 404))
        self.assertEqual((b.ok, b.error, b.status), (False, "http_5xx", 500))

    def test_timeout_is_an_error_result_and_the_browser_survives(self):
        o = BrowserOwner(lambda: PlaywrightBackend(settle_ms=0, nav_timeout_ms=500, allow=allow_local,
                                                   subresource_allow=only_local))
        try:
            slow = o.render(self.base + "/slow").result(60)
            self.assertEqual((slow.ok, slow.error), (False, "timeout"))
            self.assertTrue(o.render(self.base + "/static").result(60).ok)
        finally:
            o.shutdown()

    def test_connection_refused_is_a_network_error(self):
        r = self.owner.render("http://127.0.0.1:9/x").result(60)       # nothing listens on port 9
        self.assertEqual((r.ok, r.error), (False, "network"))
        self.assertTrue(self.render("/static").ok)                       # and the owner is fine afterwards

    def test_real_allowlist_refuses_before_navigating(self):
        o = BrowserOwner(lambda: PlaywrightBackend(settle_ms=0))        # default allowlist: *.nccu.edu.tw only
        try:
            r = o.render(self.base + "/static").result(60)
        finally:
            o.shutdown()
        self.assertEqual((r.ok, r.error), (False, "blocked_host"))

    def test_cloudflare_interstitial_is_detected_by_the_extractor(self):
        r = self.render("/cf")
        self.assertTrue(r.ok)                                            # the page loaded...
        self.assertEqual(html_to_text(r.html, r.url), ("", "cloudflare"))  # ...but it is not content

    def test_each_render_gets_a_fresh_context_no_cookie_leaks(self):
        self.render("/setcookie")
        r = self.render("/echocookie")
        self.assertIn("cookie=NONE", html_to_text(r.html, r.url)[0])


@unittest.skipUnless(FIX.exists(), "fixtures not present")
class TestFixtureEquivalence(RenderBase):
    """The recorded staff pages (rendered by Chromium in P0) served locally without their scripts: rendering them again
    and extracting must give the same text as extracting the file directly."""

    NAMES = ["11_office_註冊組.html", "12_office_教務長室.html", "17_office_出納組.html", "19_office_國際合作事務處.html"]

    @classmethod
    def setUpClass(cls):
        for n in cls.NAMES:
            raw = (FIX / n).read_bytes().decode("utf-8", "replace")
            # scripts and <img> are removed: the point is text equivalence, and an aborted external <img> (the cashier
            # page's staff-default-photo.svg) was seen to stay "pending" and hold the `load` event past 15 s -- cause
            # not investigated; it did not happen against the real site in P0 (Chromium loaded that page in ~4.6 s).
            raw = re.sub(r"<script\b.*?</script>", "", raw, flags=re.S | re.I)
            Handler.fixtures[n] = re.sub(r"<img\b[^>]*>", "", raw, flags=re.I).encode("utf-8")
        super().setUpClass()

    def test_rendered_text_equals_direct_extraction(self):
        for n in self.NAMES:
            with self.subTest(n):
                direct, _ = html_to_text(Handler.fixtures[n], "https://example.nccu.edu.tw/x")
                r = self.owner.render(f"{self.base}/fx/{n}").result(60)
                self.assertTrue(r.ok, r.detail)
                again, err = html_to_text(r.html, "https://example.nccu.edu.tw/x")
                self.assertEqual(err, "")
                c = compare(direct, again)
                self.assertTrue(c.same, f"{n}: {c.summary()}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
