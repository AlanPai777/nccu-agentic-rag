"""
experiments/live_spikes/measure_forms.py
Measure what fetching moltke forms live really costs: requests and seconds per form, with NO cache, NO LLM.
Fetches the 休學 page's three forms one after another, exactly as resource_node does (FORM_GATE off), so the
per-form numbers also say what the gate saves by skipping one.

    python experiments/live_spikes/measure_forms.py          # dry-run: lists the requests, sends nothing
    python experiments/live_spikes/measure_forms.py --run    # 3 forms x 5 requests = ~15 GETs to moltke.nccu.edu.tw
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).parent / "_out"
FORMS = ["QP-T01-02-05", "QP-T01-03-02", "QP-T01-03-04"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    run = ap.parse_args().run

    from rag.live import config
    from rag.live.fetcher import Fetcher
    from rag.live.forms import fetch_form, link_url_for

    pol = config.host_policy("moltke.nccu.edu.tw")
    if not run:
        print("DRY RUN. Would fetch, sequentially, with no cache (4 hops + 1 PDF download each, TLS verified, UA as P1):")
        for f in FORMS:
            print(f"  {link_url_for(f)}")
        print(f"~15 GETs to moltke.nccu.edu.tw; min interval {pol.min_interval:g}s, concurrency {pol.concurrency}. Pass --run.")
        return

    counts: list[str] = []
    fetcher = Fetcher(cache=None)
    original = fetcher._make_client

    def counted(host):
        c = original(host)
        c.event_hooks["request"].append(lambda req: counts.append(f"{time.monotonic():.3f} {req.url.path}"))
        return c
    fetcher._make_client = counted           # count every real HTTP request, whichever client sends it

    rows = []
    with tempfile.TemporaryDirectory() as d:
        t_all = time.monotonic()
        for fid in FORMS:
            before = len(counts)
            r = fetch_form(fid, fetcher, pdf_dir=Path(d))
            rows.append({"form": fid, "ok": r.ok, "error": r.error, "seconds": round(r.elapsed, 2),
                         "http_requests": len(counts) - before, "chars": len(r.text), "pdf_bytes": Path(r.pdf_path).stat().st_size if r.pdf_path else 0})
            print(f"  {fid}: ok={r.ok} {r.elapsed:.2f}s  {len(counts) - before} requests  {len(r.text)} chars", flush=True)
        total = time.monotonic() - t_all
    fetcher.close()
    print(f"total {total:.2f}s, {len(counts)} requests, avg {total / len(FORMS):.2f}s per form")
    OUT.mkdir(exist_ok=True)
    (OUT / "measure_forms.json").write_text(json.dumps({"total_seconds": round(total, 2), "total_requests": len(counts), "forms": rows,
                                                         "request_log": counts}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
