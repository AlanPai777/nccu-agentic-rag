"""
experiments/live_spikes/p0c_www_home.py
Phase J / P0c: is the www homepage's article list loaded by JavaScript, or are the old
/p/404-1000-N.php pages simply not linked anywhere? (docs/phase_j_live_fetch_plan.md §11.5)

ONE Chromium page load of https://www.nccu.edu.tw/ (like a human visit: the page plus the CSS/JS and
ajax modules it requests from www; HTTPS verification ON). Compares:
  * the main document exactly as the server sent it (before any JavaScript ran)  vs
  * the DOM after JavaScript finished
and, using the saved sitemap entries (_out/www_sitemap_entries.json), shows the lastmod dates of the
articles the rendered homepage links to (does the homepage only keep recent items?).

    python experiments/live_spikes/p0c_www_home.py --run
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

URL = "https://www.nccu.edu.tw/"
OUT = Path(__file__).parent / "_out"
ID = re.compile(r"/p/(404-1000-\d+)\.php")
SETTLE_MS = 4000   # ajax modules (hajaxOpenUrl) get a little longer than the usual 2 s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    if not ap.parse_args().run:
        print(f"DRY RUN. Would load {URL} once in headless Chromium (TLS verification on), "
              f"wait {SETTLE_MS} ms for ajax modules, and compare initial HTML vs rendered DOM. Pass --run.")
        return

    from playwright.sync_api import sync_playwright

    sm = {}
    f = OUT / "www_sitemap_entries.json"
    if f.exists():
        for u, lm in json.load(open(f, encoding="utf-8")):
            m = ID.search(u)
            if m:
                sm[m.group(1)] = (lm or "")[:10]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_context().new_page()
        xhr: list[str] = []
        page.on("response", lambda r: xhr.append(r.url) if "/app/index.php" in r.url else None)
        resp = page.goto(URL, timeout=60_000, wait_until="load")
        initial_html = resp.text()
        page.wait_for_timeout(SETTLE_MS)
        anchors = page.eval_on_selector_all(
            "a[href]", "els => els.map(e => [e.href, (e.innerText || '').trim().slice(0, 70)])")
        status = resp.status
        browser.close()

    init_ids = sorted(set(ID.findall(initial_html)))
    rend = [(h, t) for h, t in anchors if ID.search(h)]
    rend_ids = sorted({ID.search(h).group(1) for h, _ in rend})
    dates = collections.Counter((sm.get(i) or "not-in-sitemap")[:7] for i in rend_ids)
    more = [(h, t) for h, t in anchors if re.search(r"更多|more|歷年|校園公告|最新消息", t, flags=re.I)][:10]

    res = {
        "status": status,
        "initial_html": {"bytes": len(initial_html), "article_ids": len(init_ids), "hajaxOpenUrl_calls": initial_html.count("hajaxOpenUrl")},
        "rendered": {"anchors_total": len(anchors), "article_links": len(rend), "distinct_article_ids": len(rend_ids),
                     "lastmod_by_month_of_linked_articles": dict(sorted(dates.items())),
                     "ajax_module_responses": len(xhr)},
        "sample_article_links": [(h.split("nccu.edu.tw")[-1][:50], t) for h, t in rend[:12]],
        "more_or_list_links": [(h.split("nccu.edu.tw")[-1][:70], t) for h, t in more],
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "p0c_www_home.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
