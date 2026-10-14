"""
experiments/live_spikes/p0b_probe.py
Phase J / P0b follow-up probe (docs/phase_j_live_fetch_plan.md §11.3). Reuses the safety
rules of p0_probe.py (allowlist, request cap, TLS verification ON, no redirect following,
osa's Crawl-delay of 10 s honoured) and answers:

  1. How much of www / aca's sitemap is missing from the local corpus (coverage gap)?
     And -- using sitemap lastmod, where it is trustworthy -- how many pages changed
     since the snapshot (= measured snapshot drift)?
  2. Are the pages we actually need (aca / osa office pages from the contacts index)
     allowed by osa's and aca's full robots.txt?
  3. Does osa have a sitemap at /tw/sitemap.xml (the 301 target)?
  4. Does GET work on a www.lib content page (was the 403 HEAD-specific)?
  5. Why does cashier fail TLS verification? (one TLS handshake via the openssl CLI,
     no HTTP request; reports how many certificates the server sends and the
     issuer / AIA URL of the leaf.)

Requests: 6 HTTP GETs + 1 TLS handshake. Default is a DRY RUN; pass --run to send.
Writes only under experiments/live_spikes/_out/.

    python experiments/live_spikes/p0b_probe.py          # dry run
    python experiments/live_spikes/p0b_probe.py --run
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.robotparser import RobotFileParser

sys.path.insert(0, str(Path(__file__).parent))
import p0_probe as p0  # noqa: E402  (reuses Prober, parse_sitemap, UA, HOSTS, OUT_DIR)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = p0.OUT_DIR

# cashier's robots.txt, pasted by the user on 2026-10-14 (our httpx client cannot verify cashier's
# TLS chain, so we cannot fetch it ourselves). The "Example N" lines are comments in the original.
CASHIER_ROBOTS_PASTED = """\
# Example 1: Block only Googlebot
User-agent: Googlebot
Disallow: /intra
Disallow: /intranet

# Example 2: Block Googlebot and Adsbot
User-agent: Googlebot
User-agent: AdsBot-Google
Disallow: /intra
Disallow: /intranet

# Example 3: Block all but AdsBot crawlers
User-agent: *
Disallow: /intra
Disallow: /intranet
"""
CASHIER_STAFF_PAGE = "https://cashier.nccu.edu.tw/PageStaffing?fid=7994"   # from office_contacts_index.jsonl
LIB_CONTACT_PAGE = "https://www.lib.nccu.edu.tw/p/404-1000-312.php?Lang=zh-tw"   # from office_contacts_index.jsonl
CASHIER = "cashier.nccu.edu.tw"
ACA_XIUXUE_PAGE = "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學"


# ── offline helpers (pure, unit-testable) ────────────────────────────────────

def norm_url(u: str) -> str:
    """Comparable form: https, lower-case host, percent-decoded path, no fragment / trailing slash."""
    u = unquote(u.strip()).split("#", 1)[0]
    if u.startswith("http://"):
        u = "https://" + u[len("http://"):]
    p = urlparse(u)
    return f"{p.scheme}://{p.netloc.lower()}{p.path.rstrip('/')}" + (f"?{p.query}" if p.query else "")


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone(timedelta(hours=8)))   # sitemap dates without tz: assume Taipei


def lastmod_bins(entries: list[tuple[str, str | None]], now: datetime, snapshot: datetime | None) -> dict:
    ages = Counter()
    after_snapshot = 0
    dated = 0
    for _, lm in entries:
        d = parse_ts(lm)
        if d is None:
            continue
        dated += 1
        days = (now - d).total_seconds() / 86400
        key = ("<=1d" if days <= 1 else "<=7d" if days <= 7 else "<=30d" if days <= 30
               else "<=90d" if days <= 90 else "older")
        ages[key] += 1
        if snapshot and d > snapshot:
            after_snapshot += 1
    return {"dated": dated, "by_age": dict(ages), "modified_after_snapshot": after_snapshot}


def corpus_sets(sub: str) -> tuple[set[str], set[str], datetime | None]:
    """(urls in map.json, urls in extracted_texts.jsonl, latest ok fetched_at in map.json)."""
    mp = json.load(open(ROOT / "output" / sub / "map.json", encoding="utf-8"))
    recs = [r for r in mp if isinstance(r, dict) and "url" in r]
    in_map = {norm_url(r["url"]) for r in recs}
    last = max((parse_ts(r.get("fetched_at")) for r in recs if r.get("status") == "ok" and r.get("fetched_at")),
               default=None)
    in_text = set()
    with open(ROOT / "output" / sub / "extracted_texts.jsonl", encoding="utf-8") as f:
        for line in f:
            try:
                in_text.add(norm_url(json.loads(line)["url"]))
            except (json.JSONDecodeError, KeyError):
                pass
    return in_map, in_text, last


def robots_check(body: str, urls: list[str]) -> list[tuple[str, bool]]:
    rp = RobotFileParser()
    rp.parse(body.splitlines())
    return [(u, rp.can_fetch(p0.UA, u)) for u in urls]


def target_urls(host: str) -> list[str]:
    """Pages the 休學 chain actually needs on this host: office pages from the contacts index."""
    urls: list[str] = []
    with open(ROOT / "output" / "office_contacts_index.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if urlparse(r.get("url", "")).netloc == host and r["url"] not in urls:
                urls.append(r["url"])
    return urls


def parse_openssl_chain(text: str) -> dict:
    """From `openssl s_client -showcerts` output: how many certs the server sent, leaf subject/issuer."""
    certs = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", text, flags=re.S)
    chain_lines = re.findall(r"^\s*(\d+) s:(.*)$\n\s*i:(.*)$", text, flags=re.M)
    return {
        "certs_sent_by_server": len(certs),
        "chain": [{"depth": int(d), "subject": s.strip(), "issuer": i.strip()} for d, s, i in chain_lines],
        "verify_return": (re.search(r"Verify return code: (.*)", text) or [None, None])[1],
        "leaf_pem": certs[0] if certs else None,
    }


def leaf_aia(pem: str) -> str:
    r = subprocess.run(["openssl", "x509", "-noout", "-issuer", "-ext", "authorityInfoAccess"],
                       input=pem, capture_output=True, text=True, timeout=20)
    return (r.stdout + r.stderr).strip()


# ── the probe ────────────────────────────────────────────────────────────────

def sitemap_report(p: p0.Prober, host: str, url: str, now: datetime) -> dict:
    r = p.request("GET", url, max_bytes=p0.SITEMAP_MAX_BYTES)
    parsed = p0.parse_sitemap(r.get("_body", b"")) if r.get("status") == 200 else None
    out: dict = {"url": url, "status": r.get("status", r.get("error")), "parsed": bool(parsed)}
    if not parsed:
        return out
    sub = host.replace(".nccu.edu.tw", "")
    entries = []
    # re-read lastmod per URL (parse_sitemap keeps only summary stats)
    import gzip
    from xml.etree import ElementTree as ET
    body = r["_body"]
    body = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
    for child in ET.fromstring(body):
        loc = lm = None
        for x in child:
            tag = x.tag.rsplit("}", 1)[-1]
            if tag == "loc":
                loc = (x.text or "").strip()
            elif tag == "lastmod":
                lm = (x.text or "").strip()
        if loc:
            entries.append((loc, lm))
    in_map, in_text, snap = corpus_sets(sub)
    sm = {norm_url(u) for u, _ in entries}
    out.update({
        "kind": parsed["kind"], "n_entries": len(entries), "n_unique": len(sm),
        "in_map_json": len(sm & in_map), "in_extracted_texts": len(sm & in_text),
        "missing_from_extracted_texts": len(sm - in_text),
        "corpus_extracted_not_in_sitemap": len(in_text - sm),
        "snapshot_latest_ok_fetch": snap.isoformat() if snap else None,
        "lastmod": lastmod_bins(entries, now, snap),
        "sample_missing": sorted(sm - in_text)[:5],
    })
    (OUT_DIR / f"{sub}_sitemap_entries.json").write_text(
        json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return out


def playwright_cashier(url: str) -> dict:
    """Load one cashier page in Chromium with HTTPS verification ON (the default), extract it with the
    same extractor the index used, and diff its 5-digit extensions against the indexed snapshot."""
    from playwright.sync_api import sync_playwright
    sys.path.insert(0, str(ROOT))
    from rag.preprocess import extract_html_bytes, is_cloudflare_page

    snap = ""
    with open(ROOT / "output" / "office_contacts_index.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("url") == url:
                snap = r.get("text", "")
                break
    ext = lambda t: sorted(set(re.findall(r"(?<!\d)\d{5}(?!\d)", t)))
    out: dict = {"url": url}
    t0 = time.monotonic()
    failed: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_context().new_page()            # ignore_https_errors defaults to False
            page.on("requestfailed", lambda rq: failed.append(f"{rq.url[:80]} :: {rq.failure}"))
            resp = page.goto(url, timeout=60_000, wait_until="load")   # same wait as fetch_office_contacts.py
            page.wait_for_timeout(2000)
            html = page.content().encode("utf-8")
            out.update({"status": resp.status if resp else None, "chromium": browser.version,
                        "cloudflare_page": is_cloudflare_page(html)})
            browser.close()
        text = extract_html_bytes(html, url)
        out.update({"text_chars": len(text), "extensions_live": ext(text), "extensions_snapshot": ext(snap),
                    "extensions_only_live": sorted(set(ext(text)) - set(ext(snap))),
                    "extensions_only_snapshot": sorted(set(ext(snap)) - set(ext(text))),
                    "text_head": text[:200]})
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    out["failed_subrequests"] = failed[:5]
    out["ms"] = round((time.monotonic() - t0) * 1000)
    return out


def planned() -> list[str]:
    return [
        "GET  https://www.nccu.edu.tw/sitemap.xml            (save entries; overlap with corpus; lastmod bins)",
        "GET  https://aca.nccu.edu.tw/sitemap.xml            (same)",
        "GET  https://aca.nccu.edu.tw/robots.txt             (full body; check our aca target pages)",
        "GET  https://osa.nccu.edu.tw/robots.txt             (full body; check our osa target pages; 10 s spacing on osa)",
        "GET  https://osa.nccu.edu.tw/tw/sitemap.xml         (the 301 target found in P0; 10 s after the previous osa request)",
        f"GET  {LIB_CONTACT_PAGE}   (does GET work where HEAD / gave 403?)",
        f"TLS  openssl s_client -connect {CASHIER}:443        (handshake only, no HTTP; how many certs does the server send?)",
        f"PW   Chromium loads {CASHIER_STAFF_PAGE}   (ONE page load, like a human visit: the page plus its CSS/JS/images from cashier;"
        " HTTPS verification ON; diffs 5-digit extensions against the indexed snapshot)",
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase J P0b follow-up probe.")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()
    if not args.run:
        print("DRY RUN -- nothing is sent. Planned (6 HTTP GETs + 1 TLS handshake + 1 Chromium page load):\n")
        for line in planned():
            print("  " + line)
        print("\nSame safety rules as p0_probe.py; osa requests are spaced 10 s apart (its Crawl-delay).")
        return

    OUT_DIR.mkdir(exist_ok=True)
    p = p0.Prober()
    now = datetime.now(timezone(timedelta(hours=8)))
    res: dict = {"started": now.isoformat(timespec="seconds")}

    print("== sitemaps")
    res["sitemap_www"] = sitemap_report(p, "www.nccu.edu.tw", "https://www.nccu.edu.tw/sitemap.xml", now)
    res["sitemap_aca"] = sitemap_report(p, "aca.nccu.edu.tw", "https://aca.nccu.edu.tw/sitemap.xml", now)

    print("== robots (full) vs the pages we need")
    res["robots_check"] = {}
    for host in ("aca.nccu.edu.tw", "osa.nccu.edu.tw"):
        r = p.request("GET", f"https://{host}/robots.txt", max_bytes=300_000)
        body = r.get("_body", b"").decode("utf-8", "replace")
        urls = target_urls(host) + ([ACA_XIUXUE_PAGE] if host.startswith("aca.") else [])
        (OUT_DIR / f"{host}_robots.txt").write_text(body, encoding="utf-8")
        res["robots_check"][host] = {
            "status": r.get("status", r.get("error")),
            "results": robots_check(body, urls) if r.get("status") == 200 else None,
        }

    print("== osa sitemap (301 target)")
    r = p.request("GET", "https://osa.nccu.edu.tw/tw/sitemap.xml", max_bytes=p0.SITEMAP_MAX_BYTES)
    parsed = p0.parse_sitemap(r.get("_body", b"")) if r.get("status") == 200 else None
    res["osa_sitemap"] = {"status": r.get("status", r.get("error")), "location": r.get("location"),
                          "content_type": r.get("content_type"),
                          "parsed": {k: v for k, v in (parsed or {}).items() if k != "urls"} or None}

    print("== www.lib content page (GET)")
    r = p.request("GET", LIB_CONTACT_PAGE, max_bytes=200_000)
    res["lib_get"] = {k: v for k, v in r.items() if k != "_body"}

    print("== cashier TLS chain (handshake only)")
    try:
        proc = subprocess.run(
            ["openssl", "s_client", "-connect", f"{CASHIER}:443", "-servername", CASHIER, "-showcerts"],
            input="", capture_output=True, text=True, timeout=30)
        chain = parse_openssl_chain(proc.stdout + proc.stderr)
        if chain["leaf_pem"]:
            chain["leaf_issuer_and_aia"] = leaf_aia(chain["leaf_pem"])
        chain.pop("leaf_pem", None)
        res["cashier_tls"] = chain
    except Exception as e:
        res["cashier_tls"] = {"error": f"{type(e).__name__}: {e}"}

    print("== cashier staff page via Chromium")
    res["cashier_playwright"] = playwright_cashier(CASHIER_STAFF_PAGE)
    res["robots_check"][CASHIER] = {"status": "pasted-by-user",
                                    "results": robots_check(CASHIER_ROBOTS_PASTED, target_urls(CASHIER))}

    res["requests_sent"] = p.count
    (OUT_DIR / "p0b_raw.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("\n" + json.dumps(res, ensure_ascii=False, indent=2, default=str)[:9000])


if __name__ == "__main__":
    main()
