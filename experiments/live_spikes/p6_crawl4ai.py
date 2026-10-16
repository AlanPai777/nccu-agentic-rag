"""
experiments/live_spikes/p6_crawl4ai.py
P6: challenger B (Crawl4AI as the renderer) vs the current stack A (httpx first, Chromium only when needed).

Same 9 staff pages as measure_contacts.py, plus the 3 休學 moltke viewdetail pages (HTML only; the PDF step is not Crawl4AI's job here).
Crawl4AI renders EVERY page in Chromium (no "httpx first"), so what is compared is: does its raw HTML still go through OUR extractor and OUR
contact parser to the same result, and what does its own Markdown look like next to that. Our limiter paces request STARTS per host (osa 10 s
apart, robots/Crawl-delay as decided), and our User-Agent is used; Crawl4AI's own dispatcher is not used; its robots.txt check (Allow/Disallow only, no Crawl-delay, fails open) IS on.

    python experiments/live_spikes/p6_crawl4ai.py          # dry-run: lists what would be requested, sends nothing
    python experiments/live_spikes/p6_crawl4ai.py --run    # runs it (needs user approval: requests to nccu.edu.tw)

Result: experiments/live_spikes/_out/p6_crawl4ai.json (gitignored) + a table on stdout. Contact parsing here has NO LLM (regex tier only), so
the counts are comparable to measure_contacts.py's, which stubbed the LLM out the same way.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).parent / "_out"
OFFICES = ["註冊組", "教務長室", "住宿輔導組", "生活事務暨僑生輔導組", "原住民族學生資源中心", "身心健康中心", "出納組",
           "圖書館(各組聯絡資訊)", "國際合作事務處"]
FORMS = ["QP-T01-02-05", "QP-T01-03-02", "QP-T01-03-04"]
BASELINE_JSON = OUT / "measure_contacts_httpx_first.json"       # stack A, 2026-10-16 (contacts_parsed, chars, method per page)
FORM_ID_RE = re.compile(r"QP-[A-Z0-9]+-\d{2}-\d{2}")


def _tree_rss_mb() -> float:
    import os

    import psutil
    try:
        me = psutil.Process(os.getpid())
        return sum(p.memory_info().rss for p in [me, *me.children(recursive=True)]) / 1e6
    except Exception:                                    # noqa: BLE001
        return 0.0


async def _crawl(targets: list[tuple[str, str]], limiter, progress) -> list[dict]:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

    from rag.live import config
    from rag.live.allowlist import host_of

    # ignore_https_errors is browser-wide in Crawl4AI (stack A skips TLS verification only for cashier); True here so cashier can be read
    browser = BrowserConfig(headless=True, user_agent=config.USER_AGENT, verbose=False, ignore_https_errors=True)
    run = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, wait_until="load", page_timeout=config.REQUEST_TIMEOUT * 1000,
                           delay_before_return_html=config.RENDER_SETTLE_MS / 1000, verbose=False, check_robots_txt=True)
    t0 = time.monotonic()
    peak = {"mb": 0.0}

    async def sampler():
        while True:
            peak["mb"] = max(peak["mb"], _tree_rss_mb())
            await asyncio.sleep(0.5)

    async def one(crawler, url: str, kind: str) -> dict:
        host = host_of(url)
        # our limiter paces request STARTS per host: enter the slot (sleeps until this host may start) and leave it at once
        def reserve():
            with limiter.slot(host):
                pass
        await asyncio.to_thread(reserve)
        start = time.monotonic() - t0
        res = {"url": url, "kind": kind, "host": host, "start": round(start, 1)}
        try:
            r = await crawler.arun(url=url, config=run)
            res.update(ok=bool(r.success), status=r.status_code, error=(r.error_message or "")[:200],
                       html=r.html or "", markdown=str(r.markdown or ""),
                       raw_markdown=str(getattr(r.markdown, "raw_markdown", "") or ""))
        except Exception as e:                           # noqa: BLE001 -- failure is data
            res.update(ok=False, status=None, error=f"{type(e).__name__}: {e}"[:200], html="", markdown="", raw_markdown="")
        res["seconds"] = round(time.monotonic() - t0 - start, 1)
        progress(res)
        return res

    sampler_task = asyncio.create_task(sampler())
    try:
        async with AsyncWebCrawler(config=browser) as crawler:
            out = await asyncio.gather(*(one(crawler, u, k) for u, k in targets))
    finally:
        sampler_task.cancel()
    wall = time.monotonic() - t0
    for r in out:
        r["_wall"] = wall
        r["_peak_rss_mb"] = round(peak["mb"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    run = ap.parse_args().run

    from rag.live import config
    from rag.live.allowlist import host_of
    from rag.live.contacts import plan_pages
    from rag.live.forms import link_url_for

    pages, _ = plan_pages(OFFICES)
    targets = [(u, "staff") for u in pages] + [(link_url_for(f), "form") for f in FORMS]
    if not run:
        print("DRY RUN. Would send, through Crawl4AI's Chromium (all pages rendered, none httpx-first), our limiter pacing request starts "
              "per host, our User-Agent:")
        for u, k in targets:
            pol = config.host_policy(host_of(u))
            print(f"  GET {unquote(u)[:84]}   [{k}; {host_of(u)}: >= {pol.min_interval:g}s apart]")
        osa = sum(1 for u, _ in targets if host_of(u) == "osa.nccu.edu.tw")
        print(f"\n{len(targets)} page loads in Chromium ({osa} on osa => at least {max(0, osa - 1) * 10} s). Each load also fetches that page's own "
              "sub-resources (CSS/JS/images), like the all-Chromium run of 2026-10-16 (406 requests for 9 pages). Crawl4AI's own robots.txt "
              "check is ON (one robots.txt GET per host, Allow/Disallow only; Crawl-delay stays with our limiter). No LLM calls. Pass --run.")
        return

    from rag.live.extract import html_to_text
    from rag.live.ratelimit import RateLimiter
    import rag.skills.office_lookup_skill as skill
    from rag.skills.office_lookup_skill import parse_office_contacts

    limiter = RateLimiter()

    def progress(r):
        print(f"  {r['start']:6.1f}s start  {r['seconds']:5.1f}s  ok={r['ok']}  {r['host']:24s} {unquote(r['url'])[:60]}", file=sys.stderr)

    t = time.monotonic()
    results = asyncio.run(_crawl(targets, limiter, progress))
    wall = time.monotonic() - t

    base = {}
    if BASELINE_JSON.exists():
        base = {r["url"]: r for r in json.loads(BASELINE_JSON.read_text(encoding="utf-8"))["rows"]}
    rows = []
    with mock.patch.object(skill, "_llm_extract_contacts", lambda text: []):              # same no-LLM rule as measure_contacts.py
        for r in results:
            text, err = html_to_text(r["html"].encode("utf-8"), r["url"]) if r["html"] else ("", "no_html")
            contacts = parse_office_contacts(text) if (text and r["kind"] == "staff") else []
            md = r["markdown"]
            b = base.get(unquote(r["url"]), {})
            row = {"url": unquote(r["url"]), "kind": r["kind"], "host": r["host"], "ok": r["ok"], "status": r["status"], "error": r["error"],
                   "seconds": r["seconds"], "html_chars": len(r["html"]), "our_text_chars": len(text), "our_text_error": err,
                   "contacts_parsed": len(contacts) if r["kind"] == "staff" else None,
                   "baseline_contacts": b.get("contacts_parsed"), "baseline_chars": b.get("chars"), "baseline_method": b.get("method"),
                   "markdown_chars": len(md), "markdown_links": len(re.findall(r"\]\(https?://", md)),
                   "html_links": len(re.findall(r"<a\s[^>]*href=", r["html"], flags=re.I)),
                   "form_id_in_html": sorted(set(FORM_ID_RE.findall(r["html"]))), "form_id_in_markdown": sorted(set(FORM_ID_RE.findall(md))),
                   "goFile_in_html": len(re.findall(r"goFile\(", r["html"]))}
            rows.append(row)
            (OUT / "p6_samples").mkdir(parents=True, exist_ok=True)
            stem = re.sub(r"[^\w.-]+", "_", unquote(r["url"]).split("://")[-1])[:80]
            (OUT / "p6_samples" / f"{stem}.html").write_text(r["html"], encoding="utf-8")
            (OUT / "p6_samples" / f"{stem}.md").write_text(md, encoding="utf-8")
    peak = max((r["_peak_rss_mb"] for r in results), default=0)
    out = {"wall_seconds": round(wall, 1), "peak_rss_mb_process_tree": peak, "rows": rows}
    OUT.mkdir(exist_ok=True)
    (OUT / "p6_crawl4ai.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwall {wall:.1f}s for {len(rows)} pages; peak RSS of the process tree ~{peak} MB "
          f"(stack A for the 9 staff pages: 30.4 s, 46 requests, only oic in Chromium)\n")
    print(f"{'host':22s} {'kind':5s} {'ok':3s} {'sec':>5} {'html':>6} {'ourtxt':>6} {'md':>6} {'ppl':>4} {'A-ppl':>5} {'A-chars':>7}")
    for r in sorted(rows, key=lambda r: (r["kind"], r["host"])):
        print(f"{r['host']:22s} {r['kind']:5s} {str(r['ok'])[0]:3s} {r['seconds']:>5} {r['html_chars']:>6} {r['our_text_chars']:>6} "
              f"{r['markdown_chars']:>6} {str(r['contacts_parsed']):>4} {str(r['baseline_contacts']):>5} {str(r['baseline_chars']):>7}"
              + (f"  [{r['error'][:50]}]" if r["error"] else ""))


if __name__ == "__main__":
    main()
