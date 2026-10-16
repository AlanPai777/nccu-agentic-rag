"""
experiments/live_spikes/measure_contacts.py
P4 H5: what does reading the 休學 chain's nine staff pages live cost with "httpx first"? Uses the REAL stack (httpx fetcher with the
shared rate limiter, escalation rules A/B/C, browser-owner thread for escalated pages, fixed extractor). The contact parser's LLM
fallback is replaced by a stub that returns nothing, so this run makes NO LLM calls (the regex parse is still real, so rule C is
judged on real parse results; a page that would normally be re-read by the LLM just keeps its regex candidates here).

Reports per page: method (httpx / chromium), why it was escalated (if it was), time, requests (httpx GETs, and for escalated pages
everything Chromium loaded), state against the 2026-08-25 index. And: total requests, wall time. For comparison, the earlier
all-Chromium run (step 7, 2026-10-16): 406 requests, 35.1 s.

    python experiments/live_spikes/measure_contacts.py          # dry-run: lists what would be requested, sends nothing
    python experiments/live_spikes/measure_contacts.py --run    # runs it (needs user approval: requests to nccu.edu.tw)
"""

from __future__ import annotations

import argparse
import json
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    run = ap.parse_args().run

    from rag.live import config
    from rag.live.allowlist import host_of
    from rag.live.contacts import default_backends, fetch_contact_pages, plan_pages

    pages, _ = plan_pages(OFFICES)
    if not run:
        print("DRY RUN. Would send (httpx, rate-limited per host, default User-Agent of the live fetcher; cashier without TLS "
              "verification as decided):")
        for u, info in pages.items():
            pol = config.host_policy(host_of(u))
            print(f"  GET {unquote(u)[:84]}   [{host_of(u)}: >= {pol.min_interval:g}s apart]  offices={info['offices']}")
        osa = sum(1 for u in pages if host_of(u) == "osa.nccu.edu.tw")
        print(f"\n{len(pages)} httpx GETs ({osa} on osa.nccu.edu.tw, 10 s apart => at least {max(0, osa - 1) * 10} s). A page is then sent "
              f"to Chromium only if its static copy looks insufficient (similarity to the snapshot < {config.STATIC_SIMILARITY_MIN:g}, "
              "no content, 403, or no contact parsed). Expected from the 2026-10-14 recordings: only oic.nccu.edu.tw, which then "
              "loads its page and ~35 sub-resources in Chromium (started on demand, closed at the end). No LLM calls.")
        print("Estimated total: ~9 httpx requests + ~37 Chromium requests, wall ~31-35 s (osa floor). Not measured. Pass --run.")
        return

    import rag.skills.office_lookup_skill as skill
    from rag.live.browser import get_owner
    from rag.live.hook import get_fetcher

    fetch_static, render = default_backends()
    timeline: list[dict] = []
    t0 = time.monotonic()

    def timed_static(url):
        timeline.append({"t": round(time.monotonic() - t0, 2), "event": "httpx-start", "url": unquote(url)})
        r = fetch_static(url)
        timeline.append({"t": round(time.monotonic() - t0, 2), "event": "httpx-done", "url": unquote(url), "ok": r.ok, "error": r.error})
        return r

    def timed_render(url):
        timeline.append({"t": round(time.monotonic() - t0, 2), "event": "chromium-submit", "url": unquote(url)})
        fut = render(url)
        fut.add_done_callback(lambda f, u=url: timeline.append({"t": round(time.monotonic() - t0, 2), "event": "chromium-done", "url": unquote(u)}))
        return fut

    try:
        with mock.patch.object(skill, "_llm_extract_contacts", lambda text: []):          # no LLM in this run
            res = fetch_contact_pages(OFFICES, timed_static, timed_render)
    finally:
        get_owner().shutdown()
    wall = time.monotonic() - t0
    _ = get_fetcher

    rows = []
    for u, o in res.pages.items():
        rows.append({"url": unquote(u), "host": host_of(u), "offices": o.offices, "method": o.method, "escalated": o.escalated,
                     "state": o.state, "error": o.error, "seconds": round(o.render_seconds, 2),
                     "requests": o.requests, "static_requests_before_escalating": o.static_requests,
                     "tls_unverified": o.tls_unverified, "chars": len(o.text), "snapshot_chars": len(o.snapshot_text),
                     "contacts_parsed": len(o.handled) if isinstance(o.handled, list) else None,
                     "diff": o.comparison.summary() if o.comparison else ""})
    total_requests = sum(r["requests"] + r["static_requests_before_escalating"] for r in rows)
    out = {"wall_seconds": round(wall, 1), "total_requests": total_requests, "rows": rows, "timeline": timeline,
           "finish_order": [unquote(u) for u in res.order]}
    OUT.mkdir(exist_ok=True)
    (OUT / "measure_contacts_httpx_first.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wall {wall:.1f}s for {len(rows)} pages; total HTTP requests {total_requests} "
          f"(earlier all-Chromium run: 406 requests, 35.1 s)\n")
    print(f"{'host':26s} {'method':9s} {'state':18s} {'sec':>5} {'req':>4}  escalated / notes")
    for r in sorted(rows, key=lambda r: r["host"]):
        note = r["escalated"] + (f"  (+{r['static_requests_before_escalating']} httpx before)" if r["escalated"] else "")
        note += "  [TLS not verified]" if r["tls_unverified"] else ""
        print(f"{r['host']:26s} {r['method']:9s} {r['state']:18s} {r['seconds']:>5} {r['requests']:>4}  {note}")
    print("\ntimeline (s since start):")
    for ev in timeline:
        print(f"  {ev['t']:6.1f}  {ev['event']:15s} {ev['url'][:78]}")


if __name__ == "__main__":
    main()
