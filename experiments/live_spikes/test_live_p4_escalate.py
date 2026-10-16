"""
H1 tests: the escalation rules (rag/live/escalate.py) as pure functions, checked against the real similarity numbers
measured on the 2026-10-14 staff pages. No Chromium, no network, no LLM.
    python -W ignore -m unittest experiments.live_spikes.test_live_p4_escalate -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rag.live import config  # noqa: E402
from rag.live.escalate import post_parse_reason, pre_parse_reason, static_similarity  # noqa: E402
from rag.live.extract import html_to_text  # noqa: E402
from rag.live.fetcher import LiveResult  # noqa: E402

FIX = ROOT / "experiments" / "live_fixtures" / "chain_xiuxue_2026-10-14"
OK = lambda text: LiveResult("u", ok=True, text=text)
FAIL = lambda err, status=0: LiveResult("u", ok=False, error=err, status=status)


class TestConditionA(unittest.TestCase):
    def test_no_content_and_challenge_pages_escalate(self):
        self.assertEqual(pre_parse_reason(FAIL("empty"), None), "A:empty")
        self.assertEqual(pre_parse_reason(FAIL("cloudflare"), None), "A:cloudflare")

    def test_403_escalates_other_4xx_do_not(self):
        self.assertEqual(pre_parse_reason(FAIL("http_4xx", 403), None), "A:http_403")
        self.assertIsNone(pre_parse_reason(FAIL("http_4xx", 404), None))

    def test_an_unhappy_server_is_never_hit_again_with_a_browser(self):
        for err in ("timeout", "network", "tls", "http_429", "http_5xx", "breaker_open", "blocked_host",
                    "redirect_offsite", "too_many_redirects", "soft_404", "too_large"):
            with self.subTest(err):
                self.assertIsNone(pre_parse_reason(FAIL(err), None))


class TestConditionB(unittest.TestCase):
    def test_threshold_is_the_configured_one(self):
        self.assertEqual(config.STATIC_SIMILARITY_MIN, 0.5)
        self.assertIsNotNone(pre_parse_reason(OK("x"), 0.49))
        self.assertIsNone(pre_parse_reason(OK("x"), 0.50))
        self.assertIsNone(pre_parse_reason(OK("x"), 1.0))

    def test_no_snapshot_to_compare_means_no_b(self):
        self.assertIsNone(pre_parse_reason(OK("x"), None))

    def test_the_threshold_can_be_overridden(self):
        self.assertIsNotNone(pre_parse_reason(OK("x"), 0.8, minimum=0.9))

    def test_similarity_is_none_without_a_snapshot_or_a_live_page(self):
        self.assertIsNone(static_similarity("", OK("abc")))
        self.assertIsNone(static_similarity("abc", FAIL("timeout")))
        self.assertEqual(static_similarity("same\ntext", OK("same\ntext")), 1.0)


class TestConditionC(unittest.TestCase):
    def test_no_contacts_escalates_whatever_the_snapshot_was(self):
        self.assertEqual(post_parse_reason([]), "C:no_contacts")

    def test_some_contacts_do_not(self):
        self.assertIsNone(post_parse_reason([{"name": "x", "ext": "1"}]))

    def test_a_handler_that_returns_something_else_is_not_judged(self):
        for v in (None, "ok", {"a": 1}):
            self.assertIsNone(post_parse_reason(v))


@unittest.skipUnless(FIX.exists(), "fixtures not present")
class TestAgainstTheRecordedPages(unittest.TestCase):
    """The decision on real data: with the Chromium-rendered pages standing in for the static ones (P1: for eight of the
    nine they were identical), only the JavaScript page may escalate."""

    @classmethod
    def setUpClass(cls):
        m = json.load(open(FIX / "manifest.json", encoding="utf-8"))
        idx = {}
        with open(ROOT / "output" / "office_contacts_index.jsonl", encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                idx[d["name"]] = d["text"]
        cls.pages = {i["office"]: ((FIX / i["file"]).read_bytes(), i["url"], idx[i["office"]])
                     for i in m["items"] if i["step"] == "C" and i["office"] in idx}

    def similarity(self, office, html=None):
        raw, url, snap = self.pages[office]
        text, err = html_to_text(html if html is not None else raw, url)
        return static_similarity(snap, LiveResult(url, ok=not err, text=text, error=err))

    def test_the_eight_server_rendered_pages_stay_on_httpx(self):
        for office in self.pages:
            if office == "國際合作事務處":
                continue
            with self.subTest(office):
                sim = self.similarity(office)
                self.assertGreaterEqual(sim, 0.8, office)
                self.assertIsNone(pre_parse_reason(OK("x"), sim), office)

    def test_the_javascript_shell_of_oic_escalates_on_b_and_on_c(self):
        shell = ("<html><body><div class='item-page'>國立政治大學國際合作事務處Office of International Cooperation, "
                 "National Chengchi University</div></body></html>").encode()
        sim = self.similarity("國際合作事務處", html=shell)
        self.assertLess(sim, 0.2)
        self.assertTrue(pre_parse_reason(OK("x"), sim).startswith("B:"))
        self.assertEqual(post_parse_reason([]), "C:no_contacts")


if __name__ == "__main__":
    unittest.main(verbosity=2)
