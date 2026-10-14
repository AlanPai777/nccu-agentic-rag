"""
Offline unit tests for rag/live (Phase J P1). No network, no LLM:
  * httpx.MockTransport stands in for NCCU servers
  * recorded fixtures (experiments/live_fixtures/chain_xiuxue_2026-10-14, gitignored) supply real pages
Run:  python -m unittest experiments.live_spikes.test_live_p1 -v     (from the repo root)
Fixture-dependent tests skip themselves when the fixture directory is absent.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rag.live import config  # noqa: E402
from rag.live.allowlist import is_allowed  # noqa: E402
from rag.live.cache import LiveCache  # noqa: E402
from rag.live.compare import compare, normalize  # noqa: E402
from rag.live.fetcher import Fetcher  # noqa: E402
from rag.live.ratelimit import RateLimiter  # noqa: E402
from rag.live.resolve import LIVE_CHANGED, LIVE_INCOMPLETE, LIVE_ONLY, LIVE_SAME, SNAPSHOT_FALLBACK, resolve  # noqa: E402

FIX = ROOT / "experiments" / "live_fixtures" / "chain_xiuxue_2026-10-14"
HTML = b"<html><body><div class='item-page'><p>hello nccu</p></div></body></html>"


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.slept: list[float] = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def make_fetcher(handler, **kw):
    clock = FakeClock()
    lim = RateLimiter(clock=clock.now, sleep=clock.sleep)
    f = Fetcher(limiter=lim, transport=httpx.MockTransport(handler), sleep=clock.sleep, **kw)
    return f, clock


class TestAllowlist(unittest.TestCase):
    def test_allowed(self):
        for u in ("https://aca.nccu.edu.tw/zh/x", "http://nccu.edu.tw/", "https://WWW.NCCU.EDU.TW/p/1.php"):
            self.assertTrue(is_allowed(u), u)

    def test_blocked(self):
        for u in ("https://evil.com/", "https://nccu.edu.tw.evil.com/", "https://evilnccu.edu.tw/",
                  "ftp://aca.nccu.edu.tw/", "file:///etc/passwd", "https://u:p@aca.nccu.edu.tw/", "javascript:alert(1)", ""):
            self.assertFalse(is_allowed(u), u)


class TestNormalizeCompare(unittest.TestCase):
    def test_counter_change_is_not_a_difference(self):
        a = "原資中心\n點擊數: 61207\n分機 63001"
        b = "原資中心\n點擊數: 62459\n分機 63001"
        self.assertTrue(compare(a, b).same)
        self.assertTrue(compare("瀏覽數：44510\nx", "瀏覽數：46137\nx").same)
        self.assertTrue(compare("版權所有│使用規則 瀏覽人次: 351780 人", "版權所有│使用規則 瀏覽人次: 366983 人").same)
        self.assertTrue(compare("文章 瀏覽數: 1,234 次", "文章 瀏覽數: 9,999 次").same)

    def test_real_change_is_detected(self):
        c = compare("教務長 62160\n業務 62442", "教務長 62160")
        self.assertFalse(c.same)
        self.assertEqual(c.exts_removed, ["62442"])

    def test_form_set_change(self):
        c = compare("填 QP-T01-03-02", "填 QP-T01-03-02 與 QP-T01-03-09")
        self.assertEqual(c.forms_added, ["QP-T01-03-09"])

    def test_whitespace_only_is_same(self):
        self.assertTrue(compare("a  b\r\n\r\nc", "a b\nc").same)

    def test_static_vs_rendered_artifacts(self):
        self.assertTrue(compare("x\n您的瀏覽器不支援JavaScript功能，若網頁功能無法正常使用時，請開啟瀏覽器JavaScript狀態", "x\n瀏覽數:").same)

    def test_does_not_over_normalize(self):
        # digits in prose are not counters
        self.assertFalse(compare("名額 30 人", "名額 20 人").same)


class TestRateLimiter(unittest.TestCase):
    def test_osa_ten_second_spacing(self):
        clock = FakeClock()
        lim = RateLimiter(clock=clock.now, sleep=clock.sleep)
        starts = []
        for _ in range(3):
            with lim.slot("osa.nccu.edu.tw"):
                starts.append(clock.t)
        self.assertEqual(starts, [0.0, 10.0, 20.0])

    def test_default_one_second(self):
        clock = FakeClock()
        lim = RateLimiter(clock=clock.now, sleep=clock.sleep)
        with lim.slot("aca.nccu.edu.tw"):
            pass
        with lim.slot("aca.nccu.edu.tw"):
            pass
        self.assertEqual(clock.t, 1.0)

    def test_hosts_independent(self):
        clock = FakeClock()
        lim = RateLimiter(clock=clock.now, sleep=clock.sleep)
        with lim.slot("aca.nccu.edu.tw"):
            pass
        with lim.slot("www.nccu.edu.tw"):
            pass
        self.assertEqual(clock.t, 0.0)

    def test_global_concurrency_cap(self):
        lim = RateLimiter(global_concurrency=2, sleep=lambda s: None)
        live, peak, lock = [0], [0], threading.Lock()

        def work(h):
            with lim.slot(h):
                with lock:
                    live[0] += 1
                    peak[0] = max(peak[0], live[0])
                time.sleep(0.05)
                with lock:
                    live[0] -= 1
        ts = [threading.Thread(target=work, args=(f"h{i}.nccu.edu.tw",)) for i in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertLessEqual(peak[0], 2)

    def test_breaker_opens_and_recovers(self):
        clock = FakeClock()
        lim = RateLimiter(clock=clock.now, sleep=clock.sleep)
        for _ in range(config.BREAKER_THRESHOLD):
            lim.record_failure("x.nccu.edu.tw")
        self.assertTrue(lim.breaker_open("x.nccu.edu.tw"))
        clock.t += config.BREAKER_COOLDOWN + 1
        self.assertFalse(lim.breaker_open("x.nccu.edu.tw"))


class TestFetcher(unittest.TestCase):
    def test_ok_html(self):
        f, _ = make_fetcher(lambda r: httpx.Response(200, content=HTML, headers={"content-type": "text/html"}))
        r = f.fetch("https://aca.nccu.edu.tw/zh/a")
        self.assertTrue(r.ok, r.error)
        self.assertIn("hello nccu", r.text)

    def test_user_agent_is_original_crawler_string(self):
        seen = {}

        def h(req):
            seen["ua"] = req.headers["user-agent"]
            return httpx.Response(200, content=HTML)
        make_fetcher(h)[0].fetch("https://aca.nccu.edu.tw/a")
        self.assertEqual(seen["ua"], config.USER_AGENT)

    def test_blocked_host_sends_nothing(self):
        n = []
        f, _ = make_fetcher(lambda r: n.append(1) or httpx.Response(200, content=HTML))
        self.assertEqual(f.fetch("https://evil.com/").error, "blocked_host")
        self.assertEqual(n, [])

    def test_redirect_followed_within_allowlist(self):
        def h(req):
            if req.url.path == "/a":
                return httpx.Response(301, headers={"location": "/zh/a"})
            return httpx.Response(200, content=HTML)
        r = make_fetcher(h)[0].fetch("https://aca.nccu.edu.tw/a")
        self.assertTrue(r.ok)
        self.assertTrue(r.final_url.endswith("/zh/a"))

    def test_redirect_offsite_refused(self):
        f, _ = make_fetcher(lambda r: httpx.Response(302, headers={"location": "https://evil.com/x"}))
        self.assertEqual(f.fetch("https://aca.nccu.edu.tw/a").error, "redirect_offsite")

    def test_redirect_loop(self):
        f, _ = make_fetcher(lambda r: httpx.Response(302, headers={"location": "/a"}))
        self.assertEqual(f.fetch("https://aca.nccu.edu.tw/a").error, "too_many_redirects")

    def test_429_retry_after_then_success(self):
        calls = []

        def h(req):
            calls.append(1)
            return httpx.Response(429, headers={"retry-after": "7"}) if len(calls) == 1 else httpx.Response(200, content=HTML)
        f, clock = make_fetcher(h)
        r = f.fetch("https://aca.nccu.edu.tw/a")
        self.assertTrue(r.ok)
        self.assertEqual(r.attempts, 2)
        self.assertGreaterEqual(clock.t, 7.0)    # Retry-After was honoured

    def test_5xx_exhausts_retries(self):
        n = []
        f, _ = make_fetcher(lambda r: n.append(1) or httpx.Response(500))
        r = f.fetch("https://aca.nccu.edu.tw/a")
        self.assertEqual((r.error, r.attempts, len(n)), ("http_5xx", config.MAX_RETRIES + 1, config.MAX_RETRIES + 1))

    def test_404_not_retried(self):
        n = []
        f, _ = make_fetcher(lambda r: n.append(1) or httpx.Response(404))
        self.assertEqual(f.fetch("https://aca.nccu.edu.tw/a").error, "http_4xx")
        self.assertEqual(len(n), 1)

    def test_timeout(self):
        def h(req):
            raise httpx.ReadTimeout("slow", request=req)
        self.assertEqual(make_fetcher(h)[0].fetch("https://aca.nccu.edu.tw/a").error, "timeout")

    def test_cloudflare_page(self):
        cf = b"<html><head><script>window._cf_chl_opt={}</script></head><body>Just a moment...</body></html>"
        r = make_fetcher(lambda q: httpx.Response(200, content=cf))[0].fetch("https://aca.nccu.edu.tw/a")
        self.assertEqual(r.error, "cloudflare")

    def test_soft_404_error_page(self):
        def h(req):
            if req.url.path == "/x":
                return httpx.Response(302, headers={"location": "/ErrorPages/404.html"})
            return httpx.Response(200, content=HTML)
        self.assertEqual(make_fetcher(h)[0].fetch("https://oic.nccu.edu.tw/x").error, "soft_404")

    def test_empty_extraction(self):
        r = make_fetcher(lambda q: httpx.Response(200, content=b"<html><body></body></html>"))[0].fetch("https://aca.nccu.edu.tw/a")
        self.assertEqual(r.error, "empty")

    def test_cashier_flagged_tls_unverified_others_not(self):
        f, _ = make_fetcher(lambda q: httpx.Response(200, content=HTML))
        self.assertTrue(f.fetch("https://cashier.nccu.edu.tw/PageStaffing?fid=7994").tls_unverified)
        self.assertFalse(f.fetch("https://aca.nccu.edu.tw/a").tls_unverified)

    def test_breaker_stops_requests(self):
        n = []
        f, _ = make_fetcher(lambda r: n.append(1) or httpx.Response(500))
        for i in range(4):
            f.fetch(f"https://aca.nccu.edu.tw/p{i}")
        before = len(n)
        r = f.fetch("https://aca.nccu.edu.tw/another")
        self.assertEqual(r.error, "breaker_open")
        self.assertEqual(len(n), before)

    def test_singleflight(self):
        n = []

        def h(req):
            n.append(1)
            time.sleep(0.2)
            return httpx.Response(200, content=HTML)
        f, _ = make_fetcher(h)
        out = []
        ts = [threading.Thread(target=lambda: out.append(f.fetch("https://aca.nccu.edu.tw/a"))) for _ in range(5)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(n), 1)
        self.assertTrue(all(r.ok for r in out))

    def test_cache_hit_and_expiry(self):
        n = []
        with tempfile.TemporaryDirectory() as d:
            now = [1000.0]
            cache = LiveCache(Path(d) / "c.sqlite", clock=lambda: now[0])
            f, _ = make_fetcher(lambda r: n.append(1) or httpx.Response(200, content=HTML), cache=cache)
            f.fetch("https://aca.nccu.edu.tw/a")
            r2 = f.fetch("https://aca.nccu.edu.tw/a")
            self.assertTrue(r2.from_cache)
            self.assertEqual(len(n), 1)
            now[0] += config.TTL_SECONDS["page"] + 1
            self.assertIsNone(cache.get("https://aca.nccu.edu.tw/a"))

    def test_failure_is_not_cached(self):
        with tempfile.TemporaryDirectory() as d:
            cache = LiveCache(Path(d) / "c.sqlite")
            f, _ = make_fetcher(lambda r: httpx.Response(404), cache=cache)
            f.fetch("https://aca.nccu.edu.tw/a")
            self.assertIsNone(cache.get("https://aca.nccu.edu.tw/a"))


class TestResolve(unittest.TestCase):
    def _live(self, text, ok=True):
        from rag.live.fetcher import LiveResult
        return LiveResult("u", ok=ok, text=text, error="" if ok else "timeout")

    def test_same_uses_snapshot(self):
        r = resolve("a\n點擊數: 1", self._live("a\n點擊數: 2"))
        self.assertEqual(r.state, LIVE_SAME)
        self.assertEqual(r.text, "a\n點擊數: 1")

    def test_changed_uses_live(self):
        r = resolve("a 62442", self._live("a 62443"))
        self.assertEqual((r.state, r.text), (LIVE_CHANGED, "a 62443"))

    def test_failure_falls_back_to_snapshot(self):
        r = resolve("snap", self._live("", ok=False))
        self.assertEqual((r.state, r.text), (SNAPSHOT_FALLBACK, "snap"))

    def test_unrendered_js_page_keeps_snapshot(self):
        snap = "\n".join(f"成員{i} 分機 6{i:04d}" for i in range(40))
        r = resolve(snap, self._live("國際合作事務處\n成員 1"))
        self.assertEqual((r.state, r.text), (LIVE_INCOMPLETE, snap))

    def test_no_snapshot(self):
        self.assertEqual(resolve(None, self._live("x")).state, LIVE_ONLY)


class TestHook(unittest.TestCase):
    def test_off_returns_same_object(self):
        import os
        from rag.live.hook import apply_page
        os.environ.pop("LIVE_FETCH", None)
        p = {"url": "u", "text": "t"}
        self.assertIs(apply_page(p), p)


@unittest.skipUnless(FIX.exists(), "fixtures not present")
class TestFixtures(unittest.TestCase):
    """Real recorded pages, replayed through the real extractor."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.load(open(FIX / "manifest.json", encoding="utf-8"))

    @staticmethod
    def _snapshot(url):
        from urllib.parse import unquote
        for p in (ROOT / "output").glob("*/extracted_*.jsonl"):
            if p.parent.name not in ("aca",):
                continue
            for line in open(p, encoding="utf-8"):
                if unquote(url) in line:
                    d = json.loads(line)
                    if unquote(d["url"]) == unquote(url):
                        return d["text"]
        return None

    def test_aca_page_live_equals_snapshot(self):
        item = self.manifest["items"][0]
        snap = self._snapshot(item["url"])
        self.assertTrue(snap)
        f, _ = make_fetcher(lambda r: httpx.Response(200, content=(FIX / item["file"]).read_bytes(),
                                                     headers={"content-type": "text/html"}))
        res = resolve(snap, f.fetch(item["url"]))
        self.assertEqual(res.state, LIVE_SAME, res.comparison.summary() if res.comparison else res.live.error)

    def test_pdf_fixture_through_fetcher(self):
        item = [i for i in self.manifest["items"] if i.get("form_id") == "QP-T01-03-02"][0]
        pdf = (FIX / item["pdf"]["file"]).read_bytes()
        f, _ = make_fetcher(lambda r: httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"}))
        r = f.fetch("https://moltke.nccu.edu.tw/formservice_SSO/df?abc")
        self.assertTrue(r.ok, r.error)
        self.assertTrue(compare((FIX / item["pdf"]["text_file"]).read_text(encoding="utf-8"), r.text).same)

    def test_zhengwuzhang_drift_detected_and_others_stable(self):
        """P0 finding: 教務長室 is the one page whose live text really differs from the 8/25 index (sim 0.924);
        the counters on 原資中心 / 圖書館 must NOT count as differences."""
        idx = {}
        with open(ROOT / "output" / "office_contacts_index.jsonl", encoding="utf-8") as fh:
            for l in fh:
                d = json.loads(l)
                idx[d["name"]] = d["text"]
        from rag.preprocess import extract_html_bytes
        out = {}
        for it in self.manifest["items"]:
            if it["step"] != "C" or it["office"] not in idx:
                continue
            live = extract_html_bytes((FIX / it["file"]).read_bytes(), it["url"])
            out[it["office"]] = compare(idx[it["office"]], live)
        self.assertFalse(out["教務長室"].same)
        self.assertIn("62442", out["教務長室"].exts_removed)
        for name in ("原住民族學生資源中心", "圖書館(各組聯絡資訊)"):
            if name in out:
                self.assertEqual(out[name].exts_added + out[name].exts_removed, [], name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
