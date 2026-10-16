"""
experiments/live_spikes/p6_markdown_compare.py
P6, Markdown question: is Crawl4AI's Markdown a better thing to hand over than our extractor's text?  NO request to nccu.edu.tw: it works on
the HTML saved by p6_crawl4ai.py (_out/p6_samples/*.html), fed to Crawl4AI as raw HTML (local Chromium, no network to the site).

Per staff page, three inputs: ours (html_to_text), Crawl4AI raw Markdown, Crawl4AI fit_markdown (PruningContentFilter). For each: size, and
how many of the regex-parsed contacts' names/extensions are present. With --llm, the same LLM contact extractor the system already uses
(office_lookup_skill._llm_extract_contacts, which only reads the first 15,000 characters) is run on each input and its result counted
(Ollama cloud calls, 3 per page).

    python experiments/live_spikes/p6_markdown_compare.py            # offline: sizes + presence
    python experiments/live_spikes/p6_markdown_compare.py --llm      # + LLM extraction on each input (27 LLM calls)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).parent / "_out"
SAMPLES = OUT / "p6_samples"


async def fit_markdowns(items: dict[str, str]) -> dict[str, tuple[str, str]]:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, DefaultMarkdownGenerator, PruningContentFilter
    cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, verbose=False, check_robots_txt=False,
                           markdown_generator=DefaultMarkdownGenerator(content_filter=PruningContentFilter()))
    out = {}
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False)) as c:
        for key, html in items.items():
            r = await c.arun(url="raw:" + html, config=cfg)
            out[key] = (str(r.markdown.raw_markdown), str(r.markdown.fit_markdown or ""))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    use_llm = ap.parse_args().llm

    import rag.skills.office_lookup_skill as skill
    from rag.live.extract import html_to_text

    rows = json.loads((OUT / "p6_crawl4ai.json").read_text(encoding="utf-8"))["rows"]
    staff = [r for r in rows if r["kind"] == "staff"]
    htmls = {}
    for r in staff:
        stem = re.sub(r"[^\w.-]+", "_", r["url"].split("://")[-1])[:80]
        htmls[r["url"]] = (SAMPLES / f"{stem}.html").read_text(encoding="utf-8")
    md = asyncio.run(fit_markdowns(htmls))

    res = []
    for r in staff:
        html = htmls[r["url"]]
        ours = html_to_text(html.encode("utf-8"), r["url"])[0]
        with mock.patch.object(skill, "_llm_extract_contacts", lambda t: []):
            ref = skill.parse_office_contacts(ours)                      # regex reference set (same as the P6 table)
        names = [c["name"] for c in ref if c.get("name")]
        exts = [c["ext"] for c in ref if c.get("ext")]
        raw_md, fit_md = md[r["url"]]
        row = {"url": r["url"], "ref_contacts": len(ref)}
        for label, text in (("ours", ours), ("raw_md", raw_md), ("fit_md", fit_md)):
            row[label] = {"chars": len(text), "first15k_names": sum(n in text[:15000] for n in names), "all_names": sum(n in text for n in names),
                          "first15k_ext": sum(e in text[:15000] for e in exts), "names": len(names), "exts": len(exts)}
            if use_llm:
                try:
                    got = skill._llm_extract_contacts(text)
                except Exception as e:                                    # noqa: BLE001
                    got = []
                    row[label]["llm_error"] = f"{type(e).__name__}: {e}"[:120]
                row[label]["llm_contacts"] = len(got)
                row[label]["llm_ext_hit"] = sum(bool(c.get("ext")) and c["ext"] in exts for c in got)
        res.append(row)
        (SAMPLES / (re.sub(r"[^\w.-]+", "_", r["url"].split("://")[-1])[:80] + ".fit.md")).write_text(fit_md, encoding="utf-8")
    (OUT / "p6_markdown_compare.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    hdr = f"{'page':34s} {'ref':>3} | {'ours chars/n15k':>16} | {'raw_md chars/n15k':>18} | {'fit_md chars/n15k':>18}"
    print(hdr + (" | LLM contacts ours/raw/fit" if use_llm else ""))
    for x in res:
        line = f"{x['url'].split('//')[1][:34]:34s} {x['ref_contacts']:>3} | " + " | ".join(
            f"{x[k]['chars']:>8}/{x[k]['first15k_names']:>2}/{x[k]['names']:<2}" for k in ("ours", "raw_md", "fit_md"))
        if use_llm:
            line += " | " + "/".join(str(x[k].get("llm_contacts")) for k in ("ours", "raw_md", "fit_md"))
        print(line)


if __name__ == "__main__":
    main()
