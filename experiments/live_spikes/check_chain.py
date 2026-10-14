"""
experiments/live_spikes/check_chain.py
Phase J P1 acceptance script: for each page of the 休學 chain that httpx can fetch, take the snapshot
and the live page, extract both with the same extractor, normalize, compare. NO LLM, no mode switch.

  python experiments/live_spikes/check_chain.py             # dry-run: lists the requests it would send
  python experiments/live_spikes/check_chain.py --offline   # replay recorded fixtures (no network)
  python experiments/live_spikes/check_chain.py --run       # send the requests (needs user approval)

Targets: the aca 休學 page + the 9 office pages (static httpx fetch, so we also learn whether the
JS-rendered people pages are readable without Chromium -- plan §5.9 assumed not). moltke forms are P3.
The limiter paces requests exactly as production would (osa >= 10 s apart, global concurrency 4).
Output: experiments/live_spikes/_out/check_chain_report.{md,json}
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

from rag.live import config  # noqa: E402
from rag.live.allowlist import host_of  # noqa: E402
from rag.live.fetcher import Fetcher, LiveResult  # noqa: E402
from rag.live.resolve import resolve  # noqa: E402

FIX = ROOT / "experiments" / "live_fixtures" / "chain_xiuxue_2026-10-14"
OUT = Path(__file__).parent / "_out"
ACA_PAGE = "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學"


def office_index() -> dict[str, dict]:
    with open(ROOT / "output" / "office_contacts_index.jsonl", encoding="utf-8") as fh:
        return {d["name"]: d for d in map(json.loads, fh)}


def aca_snapshot(url: str) -> str | None:
    target = unquote(url)
    with open(ROOT / "output" / "aca" / "extracted_texts.jsonl", encoding="utf-8") as fh:
        for line in fh:
            if target in unquote(line[:400]) or target in line:
                d = json.loads(line)
                if unquote(d["url"]) == target:
                    return d["text"]
    return None


def targets() -> list[dict]:
    manifest = json.load(open(FIX / "manifest.json", encoding="utf-8"))
    idx = office_index()
    t = [{"label": "aca 休學規定頁", "url": ACA_PAGE, "snapshot": aca_snapshot(ACA_PAGE), "fixture": "01_aca_xiuxue.html"}]
    for it in manifest["items"]:
        if it["step"] == "C" and it["office"] in idx:
            t.append({"label": f"人員頁 {it['office']}", "url": it["url"], "snapshot": idx[it["office"]]["text"],
                      "fixture": it["file"]})
    return t


def offline_fetch(t: dict) -> LiveResult:
    from rag.preprocess import extract_html_bytes
    text = extract_html_bytes((FIX / t["fixture"]).read_bytes(), t["url"])
    return LiveResult(t["url"], ok=bool(text.strip()), text=text, status=200, error="" if text.strip() else "empty")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    ts = targets()
    if not (a.run or a.offline):
        print("DRY RUN. Would send these httpx GETs (TLS verification on except cashier; redirects followed within *.nccu.edu.tw):")
        for t in ts:
            pol = config.host_policy(host_of(t["url"]))
            print(f"  GET {unquote(t['url'])[:90]}   [{host_of(t['url'])}: >= {pol.min_interval:g}s apart]")
        print(f"{len(ts)} requests, global concurrency {config.GLOBAL_CONCURRENCY}, timeout {config.REQUEST_TIMEOUT:g}s, "
              f"retries {config.MAX_RETRIES}. Pass --run to send, or --offline to replay fixtures.")
        return

    t0 = time.monotonic()
    if a.offline:
        results = {t["url"]: offline_fetch(t) for t in ts}
    else:
        f = Fetcher()                      # no cache: we want real timings
        results = f.fetch_many([t["url"] for t in ts])
    wall = time.monotonic() - t0

    rows = []
    for t in ts:
        live = results[t["url"]]
        r = resolve(t["snapshot"], live)
        rows.append({
            "label": t["label"], "url": unquote(t["url"]), "state": r.state, "http": live.status,
            "ms": round(live.elapsed * 1000), "attempts": live.attempts, "error": live.error, "detail": live.detail,
            "redirects": [unquote(x) for x in live.redirects], "tls_unverified": live.tls_unverified,
            "snapshot_chars": len(t["snapshot"] or ""), "live_chars": len(live.text),
            "diff": r.comparison.summary() if r.comparison else "",
            "lines_added": r.comparison.lines_added if r.comparison else [],
            "lines_removed": r.comparison.lines_removed if r.comparison else [],
        })
    mode = "offline (fixtures, Chromium-rendered)" if a.offline else "live httpx (static HTML)"
    md = [f"# check_chain ({mode}) {time.strftime('%Y-%m-%d %H:%M:%S')}", "",
          f"wall {wall:.1f}s, {len(rows)} pages", "",
          "| page | state | http | ms | diff |", "|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['label']} | {r['state']}{' (TLS unverified)' if r['tls_unverified'] else ''} | {r['http']} | "
                  f"{r['ms']} | {r['error'] or r['diff']} |")
    md.append("")
    for r in rows:
        if r["lines_added"] or r["lines_removed"]:
            md += [f"## {r['label']}", *[f"- `-` {x}" for x in r["lines_removed"]], *[f"- `+` {x}" for x in r["lines_added"]], ""]
    OUT.mkdir(exist_ok=True)
    name = "check_chain_offline" if a.offline else "check_chain"
    (OUT / f"{name}_report.md").write_text("\n".join(md), encoding="utf-8")
    (OUT / f"{name}_report.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
