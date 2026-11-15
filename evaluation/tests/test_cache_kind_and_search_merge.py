"""
Offline checks for three fixes of 2026-11-15 (plan F35, F36, F37). No LLM, no network (the transport is a mock that records its calls).
F35: the live cache is keyed by url alone; a plain-text page row stored under a moltke form url made fetch_form crash on json.loads.
F36: the form text the agent reads carries the official download link as its own line.
F37: search_texts also searches the question as asked and merges the result lists.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["LIVE_BROWSER"] = "off"
os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")
import helpers

ROOT = helpers.ROOT
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from rag.live.cache import CacheRow, LiveCache
from rag.live.fetcher import Fetcher
from rag.live import forms
from rag.live.forms import fetch_form, link_url_for
from rag.agentic.tools import form as form_tool
from rag.agentic.tools import search as search_tool

FID = "QP-M03-01-05"


def _row(url, kind, text):
    return CacheRow(url, kind, url, 1000.0, 200, "h", "h", text, None, False)


class CacheKindTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = LiveCache(Path(self.tmp.name) / "c.sqlite", clock=lambda: 1001.0)
        self.calls = []

        def handler(req):
            self.calls.append(str(req.url))
            return httpx.Response(500)
        self.fetcher = Fetcher(cache=self.cache, transport=httpx.MockTransport(handler), sleep=lambda s: None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_page_row_under_the_form_url_is_a_miss_not_a_crash(self):
        self.cache.put(_row(link_url_for(FID), "page", "申請方式：請至教務處辦理（純文字，不是 JSON）"), ttl=3600)
        f = fetch_form(FID, self.fetcher)           # used to raise json.JSONDecodeError
        self.assertFalse(f.from_cache)
        self.assertTrue(self.calls, "a miss must go to the site (the mock answers 500, so the result is an error, not a crash)")

    def test_a_broken_form_row_is_also_a_miss(self):
        self.cache.put(_row(link_url_for(FID), "form", "{not json"), ttl=3600)
        self.assertFalse(fetch_form(FID, self.fetcher).from_cache)
        self.cache.put(_row(link_url_for(FID), "form", '{"title": "x"}'), ttl=3600)      # JSON but keys missing
        self.assertFalse(fetch_form(FID, self.fetcher).from_cache)

    def test_a_good_form_row_is_still_served_from_the_cache(self):
        packed = '{"title": "T", "unit": "U", "text": "全文", "discontinued": false}'
        self.cache.put(_row(link_url_for(FID), "form", packed), ttl=3600)
        f = fetch_form(FID, self.fetcher)
        self.assertTrue(f.from_cache)
        self.assertEqual((f.title, f.text), ("T", "全文"))
        self.assertEqual(self.calls, [])

    def test_the_fetcher_does_not_serve_a_row_of_another_kind_as_a_page(self):
        url = "https://aca.nccu.edu.tw/x"
        self.cache.put(_row(url, "form", '{"title": "T"}'), ttl=3600)
        r = self.fetcher.fetch(url, kind="page")
        self.assertFalse(r.from_cache)
        self.assertTrue(self.calls)

    def test_the_fetcher_still_serves_a_row_of_its_own_kind(self):
        url = "https://aca.nccu.edu.tw/x"
        self.cache.put(_row(url, "page", "內文"), ttl=3600)
        r = self.fetcher.fetch(url, kind="page")
        self.assertTrue(r.from_cache)
        self.assertEqual(r.text, "內文")
        self.assertEqual(self.calls, [])


class DownloadLineTest(unittest.TestCase):
    def test_a_live_form_text_carries_the_official_link_right_after_the_marker_line(self):
        want = f"下載連結：{link_url_for(FID)}"
        for f in ({"form_title": "T", "text": "本文", "live_marker": "[live:src status=live_same]"},
                  {"form_title": "T", "text": "本文", "live_marker": "[m]", "discontinued": True}):
            lines = form_tool._tool_text(f, FID).split("\n")
            self.assertEqual(lines[1], f["live_marker"])          # the marker stays on the second line, where the ledger reads it
            self.assertEqual(lines[2], want)

    def test_the_text_without_live_and_the_error_text_are_unchanged(self):
        self.assertEqual(form_tool._tool_text({"form_title": "T", "text": "本文"}, FID), "get_form 取得表單 T\n\n本文")
        self.assertNotIn("下載連結", form_tool._tool_text({"error": "nope"}, FID))

    def test_without_a_form_id_nothing_is_added(self):
        self.assertNotIn("下載連結", form_tool._tool_text({"form_title": "T", "text": "本文", "live_marker": "[m]"}))


def _c(url, n, chunk=0):
    return {"url": url, "title": url, "subdomain": "aca", "bm25_score": 1.0, "text_clean": "", "chunk_index": chunk, "n": n}


class SearchMergeTest(unittest.TestCase):
    def test_interleaved_each_lists_top_hit_first_and_duplicates_dropped(self):
        a = [_c("a1", 1), _c("a2", 2), _c("shared", 3)]
        b = [_c("b1", 1), _c("shared", 2), _c("b3", 3)]
        urls = [c["url"] for c in search_tool._merge_candidates(a, b)]
        self.assertEqual(urls, ["a1", "b1", "a2", "shared", "b3"])

    def test_empty_side(self):
        a = [_c("a1", 1)]
        self.assertEqual(search_tool._merge_candidates(a, []), a)
        self.assertEqual(search_tool._merge_candidates([], a), a)

    def test_search_texts_searches_the_original_question_too_and_judges_the_merged_list(self):
        asked = []

        class KS:
            def __init__(self, db_path=None):
                pass

            def search(self, q, top_k=5, subdomain=None):
                asked.append(q)
                return [_c("rw", 1)] if q == "跨校雙主修 審核單位" else [_c("orig", 1)]
        seen = {}

        def judge(query, cands):
            seen["urls"] = [c["url"] for c in cands]
            return {"good_enough": True, "selected_index": 2, "reason": "r"}
        state = {"rewritten": "跨校雙主修 審核單位", "query": "台聯大跨校雙主修的審核單位是誰", "subdomain_hint": None, "live": None}
        with mock.patch.object(search_tool, "KeywordStore", KS), mock.patch.object(search_tool, "_judge_candidates", judge):
            out = search_tool.search_texts.func(state) if hasattr(search_tool.search_texts, "func") else search_tool.search_texts(state)
        self.assertEqual(asked, ["跨校雙主修 審核單位", "台聯大跨校雙主修的審核單位是誰"])
        self.assertEqual(seen["urls"], ["rw", "orig"])
        self.assertIn("URL: orig", out)

    def test_same_query_is_searched_once(self):
        asked = []

        class KS:
            def __init__(self, db_path=None):
                pass

            def search(self, q, top_k=5, subdomain=None):
                asked.append(q)
                return [_c("x", 1)]
        state = {"rewritten": "休學", "query": "休學", "subdomain_hint": None}
        with mock.patch.object(search_tool, "KeywordStore", KS), \
             mock.patch.object(search_tool, "_judge_candidates", lambda q, c: {"good_enough": True, "selected_index": 1, "reason": ""}):
            search_tool.search_texts.func(state) if hasattr(search_tool.search_texts, "func") else search_tool.search_texts(state)
        self.assertEqual(asked, ["休學"])


if __name__ == "__main__":
    unittest.main()
