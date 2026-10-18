"""
Offline tests for P8 step S0: extract_links_tool reads the page as the live check left it (docs/phase_j_live_fetch_plan.md, P8.3 S0).
No network, no LLM: httpx.MockTransport stands in for NCCU.   Run from the repo root:
    LANGFUSE_TRACING_ENABLED=false python -W ignore -m unittest experiments.live_spikes.test_live_s0_extract_links -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rag import agent_tools  # noqa: E402
from rag.agentic.tools import page as page_tool  # noqa: E402
from rag.live import hook  # noqa: E402
from rag.live.cache import LiveCache  # noqa: E402
from rag.live.fetcher import Fetcher  # noqa: E402
from rag.live.ratelimit import RateLimiter  # noqa: E402

URL = "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學"
OLD = "https://osa.nccu.edu.tw/old-page"
NEW = "https://osa.nccu.edu.tw/new-page"
SNAP = {"url": URL, "title": "休學", "subdomain": "aca",
        "text": f"申請前請看 [舊連結]({OLD}) 與 [首頁](https://aca.nccu.edu.tw/)。 reg ext 62160"}


def page_html(body: str) -> bytes:
    return f"<html><body><div class='item-page'><p>{body}</p></div></body></html>".encode()


def run_tool(snapshot=SNAP):
    with mock.patch.object(page_tool, "_get_page_raw", lambda url, subdomain=None: dict(snapshot)):
        return page_tool.extract_links_tool.func(URL, {"subdomain_hint": None})


class TestLinksFromText(unittest.TestCase):
    def test_dedupes_keeps_order_and_only_nccu(self):
        text = "[a](https://x.nccu.edu.tw/1) [b](https://example.com/2) [c](https://x.nccu.edu.tw/1) [d](https://y.nccu.edu.tw/3)"
        self.assertEqual([l["url"] for l in agent_tools.links_from_text(text)], ["https://x.nccu.edu.tw/1", "https://y.nccu.edu.tw/3"])

    def test_extract_links_unchanged_for_a_snapshot_page(self):
        # extract_links (the snapshot function) now delegates to links_from_text: same result as before for a real corpus page
        page = agent_tools.get_page(URL)
        if "error" in page:
            self.skipTest("corpus page not available")
        self.assertEqual(agent_tools.extract_links(URL), agent_tools.links_from_text(page["text"]))


class TestOff(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"LIVE_FETCH": "off"})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_output_is_the_snapshot_links_in_the_old_format(self):
        out = run_tool()
        self.assertEqual(out, f"extract_links 找到:\n- 舊連結: {OLD}\n- 首頁: https://aca.nccu.edu.tw/")

    def test_no_request_is_made(self):
        hits = []
        hook._fetcher = Fetcher(limiter=RateLimiter(sleep=lambda s: None),
                                transport=httpx.MockTransport(lambda r: hits.append(r) or httpx.Response(200, content=page_html("x"))),
                                sleep=lambda s: None)
        try:
            run_tool()
        finally:
            hook._fetcher = None
        self.assertEqual(hits, [])

    def test_no_links_and_unknown_page(self):
        self.assertEqual(run_tool(dict(SNAP, text="no links here")), "extract_links 找到 0 個連結")
        self.assertEqual(run_tool({"error": "not in corpus"}), "extract_links 找到 0 個連結")


class TestOn(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"LIVE_FETCH": "on"})
        self._env.start()
        self.hits = []

    def tearDown(self):
        self._env.stop()
        hook._fetcher = None

    def use(self, handler, cache=None):
        def counted(r):
            self.hits.append(str(r.url))
            return handler(r)
        hook._fetcher = Fetcher(limiter=RateLimiter(sleep=lambda s: None), cache=cache, transport=httpx.MockTransport(counted),
                                sleep=lambda s: None)

    def test_a_link_added_on_the_live_page_is_found(self):
        self.use(lambda r: httpx.Response(200, content=page_html(f"申請前請看 [新連結]({NEW}) 與 [首頁](https://aca.nccu.edu.tw/)。 reg ext 62160")))
        out = run_tool()
        self.assertIn(f"- 新連結: {NEW}", out)
        self.assertNotIn(OLD, out)             # the live page no longer lists it: the snapshot's old link must not come back

    def test_unchanged_live_page_gives_the_snapshot_links(self):
        self.use(lambda r: httpx.Response(200, content=page_html(SNAP["text"])))
        self.assertEqual(run_tool(), f"extract_links 找到:\n- 舊連結: {OLD}\n- 首頁: https://aca.nccu.edu.tw/")

    def test_live_failure_falls_back_to_the_snapshot_links(self):
        self.use(lambda r: httpx.Response(404))
        self.assertIn(f"- 舊連結: {OLD}", run_tool())

    def test_get_page_then_extract_links_makes_one_request(self):
        """The agent reads the page, then asks for its links: the side cache must answer the second call."""
        with tempfile.TemporaryDirectory() as d:
            self.use(lambda r: httpx.Response(200, content=page_html(SNAP["text"])), cache=LiveCache(Path(d) / "live.sqlite"))
            with mock.patch.object(page_tool, "_get_page_raw", lambda url, subdomain=None: dict(SNAP)):
                page_tool.get_page_tool.func(URL, {"subdomain_hint": None})
                page_tool.extract_links_tool.func(URL, {"subdomain_hint": None})
            self.assertEqual(len(self.hits), 1, self.hits)


if __name__ == "__main__":
    unittest.main()
