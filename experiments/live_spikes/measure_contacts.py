"""
experiments/live_spikes/measure_contacts.py
P4 step 7: what does reading the 休學 chain's nine staff pages live really cost? Uses the REAL stack (browser-owner thread,
scheduler, shared rate limiter, fixed extractor) on the nine index pages, with NO parsing and NO LLM (handler is a no-op).
Reports per page: render time, the HTTP requests the page made (and how many went to *.nccu.edu.tw -- a page visit loads
images/CSS/JS, not just the HTML), the state against the 2026-08-25 index, and for the whole run: wall time and the order
the scheduler chose.

    python experiments/live_spikes/measure_contacts.py          # dry-run: lists what would be loaded, sends nothing
    python experiments/live_spikes/measure_contacts.py --run    # loads the nine pages in Chromium (needs user approval)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).parent / "_out"
OFFICES = ["註冊組", "教務長室", "住宿輔導組", "生活事務暨僑生輔導組", "原住民族學生資源中心", "身心健康中心", "出納組",
           "圖書館(各組聯絡資訊)", "國際合作事務處"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    run = ap.parse_args().run

    from rag.live import config
    from rag.live.allowlist import host_of
    from rag.live.contacts import fetch_contact_pages, plan_pages
    from rag.live.schedule import RenderScheduler

    pages, uncovered = plan_pages(OFFICES)
    if not run:
        print("DRY RUN. Would load these pages in headless Chromium (TLS verified, default Chromium UA, load + "
              f"{config.RENDER_SETTLE_MS} ms settle, fresh context each, no parsing, no LLM):")
        for u, info in pages.items():
            pol = config.host_policy(host_of(u))
            print(f"  {unquote(u)[:84]}   [{host_of(u)}: >= {pol.min_interval:g}s apart]  offices={info['offices']}")
        osa = sum(1 for u in pages if host_of(u) == "osa.nccu.edu.tw")
        print(f"\n{len(pages)} page loads ({osa} on osa.nccu.edu.tw, 10 s apart => at least {max(0, osa - 1) * 10} s of waiting). "
              "Each load also fetches the page's images/CSS/JS (the fixtures show roughly 10-70 sub-requests per page); the "
              "run counts them. Wall time estimate 33-50 s (simulation + P0 numbers; not measured).")
        print("Pass --run to load them.")
        return

    from rag.live.browser import get_owner
    from rag.live.hook import get_fetcher

    owner, limiter = get_owner(), get_fetcher().limiter
    t0 = time.monotonic()
    timeline: list[dict] = []

    def submit(url: str):
        timeline.append({"t": round(time.monotonic() - t0, 2), "event": "submit", "url": unquote(url)})
        fut = owner.render(url)
        fut.add_done_callback(lambda f, u=url: timeline.append({"t": round(time.monotonic() - t0, 2), "event": "done", "url": unquote(u)}))
        return fut

    sched = RenderScheduler(submit, limiter)
    try:
        res = fetch_contact_pages(OFFICES, sched, handler=lambda o: None)
    finally:
        owner.shutdown()
    wall = time.monotonic() - t0

    rows = []
    for u in sched.order:
        o = res.pages[u]
        rows.append({"url": unquote(u), "host": host_of(u), "offices": o.offices, "state": o.state, "error": o.error,
                     "render_s": round(o.render_seconds, 2), "requests": o.requests, "requests_nccu": o.requests_nccu, "chars": len(o.text), "snapshot_chars": len(o.snapshot_text),
                     "diff": o.comparison.summary() if o.comparison else ""})
    out = {"wall_seconds": round(wall, 1), "order": [unquote(u) for u in sched.order], "rows": rows, "timeline": timeline}
    OUT.mkdir(exist_ok=True)
    (OUT / "measure_contacts.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wall {wall:.1f}s for {len(rows)} pages (this includes the scheduler's waits for osa's 10 s gaps)\n")
    print(f"{'#':>2} {'host':26s} {'state':18s} {'render_s':>8} {'requests(all/nccu)':>19} {'chars(live/snap)':>17}  offices")
    for i, r in enumerate(rows, 1):
        req = f"{r['requests']}/{r['requests_nccu']}"
        print(f"{i:>2} {r['host']:26s} {r['state']:18s} {r['render_s']:>8} {req:>19} {r['chars']:>8}/{r['snapshot_chars']:<8} {r['offices']}")
    print(f"\ntotal HTTP requests made by the nine page loads: {sum(r['requests'] for r in rows)} "
          f"(to *.nccu.edu.tw: {sum(r['requests_nccu'] for r in rows)})")
    print("\nstart/finish timeline (seconds since the first submit):")
    for ev in timeline:
        print(f"  {ev['t']:6.1f}  {ev['event']:6s} {ev['url'][:80]}")


if __name__ == "__main__":
    main()
