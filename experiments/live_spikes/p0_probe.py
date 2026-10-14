"""
experiments/live_spikes/p0_probe.py
Phase J / P0 read-only probe (docs/phase_j_live_fetch_plan.md §6 P0, §7).

Per NCCU host, answers: is there a robots.txt (and what does it say)? a
sitemap (what kind, how many URLs, is lastmod usable)? are the sitemap's URLs
alive? do pages send ETag / Last-Modified? does the server answer 200 for a
path that cannot exist (soft 404)? which IPs do the hosts resolve to?

Safety:
  * default is a DRY RUN -- prints the requests it would send and sends nothing.
    Pass --run to actually send.
  * only the hosts listed in HOSTS are ever contacted (anything else is skipped).
  * sequential, >= MIN_INTERVAL seconds between requests to the same host,
    TLS verification stays ON, redirects are NOT followed (they are recorded),
    at most MAX_REQUESTS requests in total.
  * writes only under experiments/live_spikes/_out/. Never touches output/ or rag/.

Usage:
    python experiments/live_spikes/p0_probe.py           # dry run
    python experiments/live_spikes/p0_probe.py --run     # send the requests
"""

from __future__ import annotations

import argparse
import gzip
import json
import socket
import ssl
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET

import httpx

# Same identity the original crawl used (NCCU-Crawler/downloader.py) -- plan decision D11, option A.
UA = "Mozilla/5.0 (compatible; NCCU-Edu-Crawler/1.0; +https://www.nccu.edu.tw) Academic research bot"

HOSTS = [
    "www.nccu.edu.tw", "aca.nccu.edu.tw", "osa.nccu.edu.tw", "cashier.nccu.edu.tw",
    "www.lib.nccu.edu.tw", "oic.nccu.edu.tw", "moltke.nccu.edu.tw",
]

# Representative pages for the ETag / Last-Modified check (HEAD; GET fallback if HEAD is refused).
HEAD_TARGETS = [
    "https://www.nccu.edu.tw/",
    "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學",
    "https://aca.nccu.edu.tw/zh/最新消息",
    "https://osa.nccu.edu.tw/tw",
    "https://cashier.nccu.edu.tw/",
    "https://www.lib.nccu.edu.tw/",
    "https://oic.nccu.edu.tw/",
    "https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-03-02",
]

SAMPLE_WWW = 10      # sitemap URLs requested for www (is the 238/240-are-404 pattern real?)
SAMPLE_OTHER = 5     # ... for any other host that turns out to have a sitemap
TIMEOUT = 60.0       # per request (plan D8)
MIN_INTERVAL = 1.0   # seconds between requests to the same host
MAX_REQUESTS = 90    # hard stop
SITEMAP_MAX_BYTES = 5_000_000
OUT_DIR = Path(__file__).parent / "_out"
SOFT404_PATH = "/__live_probe_nonexistent_404__"


# ── parsing helpers (pure functions, unit-testable offline) ──────────────────

def looks_like_html(body: bytes) -> bool:
    head = body[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<head" in head


def parse_robots(text: str) -> dict:
    """Summarise a robots.txt body. Uses the stdlib parser for Crawl-delay / can_fetch."""
    lines = [ln.strip() for ln in text.splitlines()]
    sitemaps = [ln.split(":", 1)[1].strip() for ln in lines if ln.lower().startswith("sitemap:")]
    disallows = [ln for ln in lines if ln.lower().startswith("disallow:") and ln.split(":", 1)[1].strip()]
    rp = RobotFileParser()
    rp.parse(lines)
    return {
        "sitemap_lines": sitemaps,
        "n_disallow": len(disallows),
        "disallow_sample": disallows[:5],
        "crawl_delay": rp.crawl_delay("*"),
        "can_fetch_root": rp.can_fetch(UA, "/"),
        "first_lines": lines[:8],
    }


def parse_sitemap(body: bytes) -> dict | None:
    """Parse <urlset> or <sitemapindex> (gzip tolerated). Returns None if it is not XML."""
    if body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except OSError:
            return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    local = lambda el: el.tag.rsplit("}", 1)[-1]
    kind = local(root)
    if kind not in ("urlset", "sitemapindex"):
        return None
    entries = []
    for child in root:
        loc = lastmod = None
        for sub in child:
            if local(sub) == "loc":
                loc = (sub.text or "").strip()
            elif local(sub) == "lastmod":
                lastmod = (sub.text or "").strip()
        if loc:
            entries.append((loc, lastmod))
    mods = [m for _, m in entries if m]
    return {
        "kind": kind,
        "n": len(entries),
        "urls": [u for u, _ in entries],
        "n_lastmod": len(mods),
        "lastmod_min": min(mods) if mods else None,
        "lastmod_max": max(mods) if mods else None,
        "lastmod_distinct": len(set(mods)),
        # every entry sharing one timestamp usually means "when the file was generated"
        "lastmod_all_same": bool(mods) and len(set(mods)) == 1,
    }


def pick_sample(urls: list[str], n: int) -> list[str]:
    if not urls or n <= 0:
        return []
    step = max(1, len(urls) // n)
    return urls[::step][:n]


# ── network layer ────────────────────────────────────────────────────────────

class Prober:
    def __init__(self) -> None:
        self.clients: dict[str, httpx.Client] = {}
        self.last_hit: dict[str, float] = {}
        self.count = 0

    def client(self, host: str) -> httpx.Client:
        if host not in self.clients:
            verify: bool | ssl.SSLContext = True
            if host.startswith("moltke."):
                # moltke uses legacy TLS renegotiation (see rag/fetch_moltke_forms.py); verification stays ON.
                ctx = ssl.create_default_context()
                ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
                verify = ctx
            self.clients[host] = httpx.Client(
                headers={"User-Agent": UA}, timeout=TIMEOUT, verify=verify, follow_redirects=False)
        return self.clients[host]

    def request(self, method: str, url: str, max_bytes: int = 4096) -> dict:
        host = urlparse(url).netloc
        if host not in HOSTS:
            return {"url": url, "method": method, "skipped": "host not in allowlist"}
        if self.count >= MAX_REQUESTS:
            return {"url": url, "method": method, "skipped": "MAX_REQUESTS reached"}
        gap = time.monotonic() - self.last_hit.get(host, -1e9)
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)
        self.count += 1
        t0 = time.monotonic()
        rec: dict = {"url": url, "method": method}
        try:
            with self.client(host).stream(method, url) as resp:
                body = b""
                if method != "HEAD":
                    for chunk in resp.iter_bytes():
                        body += chunk
                        if len(body) >= max_bytes:
                            break
                h = resp.headers
                rec.update({
                    "status": resp.status_code,
                    "content_type": h.get("content-type"),
                    "location": h.get("location"),
                    "etag": h.get("etag"),
                    "last_modified": h.get("last-modified"),
                    "cache_control": h.get("cache-control"),
                    "server": h.get("server"),
                    "via_or_cdn": {k: h.get(k) for k in ("via", "x-cache", "cf-ray", "x-azure-ref", "x-powered-by") if h.get(k)},
                    "bytes_read": len(body),
                    "truncated": len(body) >= max_bytes,
                    "_body": body,
                })
        except Exception as e:  # recorded, never raised: a failed probe is itself a result
            rec["error"] = f"{type(e).__name__}: {e}"
        rec["ms"] = round((time.monotonic() - t0) * 1000)
        self.last_hit[host] = time.monotonic()
        tag = rec.get("status", rec.get("error", rec.get("skipped")))
        print(f"  [{self.count:2d}] {method:4s} {tag!s:>6}  {rec['ms']:5d} ms  {url[:90]}", flush=True)
        return rec


def resolve(host: str) -> list[str]:
    """DNS lookup only (not an HTTP request) -- do the hosts share IPs?"""
    try:
        return sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    except OSError as e:
        return [f"DNS error: {e}"]


def strip_body(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k != "_body"}


# ── the probe itself ─────────────────────────────────────────────────────────

def probe_host(p: Prober, host: str) -> dict:
    out: dict = {"host": host, "ips": resolve(host)}
    origin = f"https://{host}"

    r = p.request("GET", f"{origin}/robots.txt", max_bytes=200_000)
    body = r.get("_body", b"")
    robots = strip_body(r)
    if "status" in r and r["status"] == 200:
        html = looks_like_html(body) or "html" in (r.get("content_type") or "").lower()
        robots["looks_like_html"] = html
        if not html:
            robots["parsed"] = parse_robots(body.decode("utf-8", "replace"))
    out["robots"] = robots

    candidates = []
    for line in (robots.get("parsed") or {}).get("sitemap_lines", []):
        if urlparse(line).netloc in HOSTS and line not in candidates:
            candidates.append(line)
    for path in ("/sitemap.xml", "/sitemap_index.xml"):
        if f"{origin}{path}" not in candidates:
            candidates.append(f"{origin}{path}")

    out["sitemap"] = {"tried": []}
    for cand in candidates:
        r = p.request("GET", cand, max_bytes=SITEMAP_MAX_BYTES)
        info = strip_body(r)
        parsed = parse_sitemap(r.get("_body", b"")) if r.get("status") == 200 else None
        if parsed:
            info["parsed"] = {k: v for k, v in parsed.items() if k != "urls"}
            out["sitemap"]["tried"].append(info)
            urls = parsed["urls"]
            if parsed["kind"] == "sitemapindex" and urls:   # look inside only the first child
                child = p.request("GET", urls[0], max_bytes=SITEMAP_MAX_BYTES)
                cparsed = parse_sitemap(child.get("_body", b"")) if child.get("status") == 200 else None
                info["first_child"] = {"url": urls[0], **strip_body(child),
                                       "parsed": {k: v for k, v in (cparsed or {}).items() if k != "urls"}}
                urls = (cparsed or {}).get("urls", [])
            out["sitemap"]["found"] = cand
            out["sitemap"]["n_urls_seen"] = len(urls)
            out["sitemap"]["slash_p_slash_p"] = sum("/p/p/" in u for u in urls)
            n = SAMPLE_WWW if host == "www.nccu.edu.tw" else SAMPLE_OTHER
            samples = []
            for u in pick_sample(urls, n):
                upgraded = u.startswith("http://")
                url = ("https://" + u[len("http://"):]) if upgraded else u
                s = strip_body(p.request("GET", url, max_bytes=2048))
                s["upgraded_http_to_https"] = upgraded
                samples.append(s)
            out["sitemap"]["samples"] = samples
            break
        out["sitemap"]["tried"].append(info)

    out["soft404"] = strip_body(p.request("GET", f"{origin}{SOFT404_PATH}", max_bytes=2048))
    return out


def probe_head_targets(p: Prober) -> list[dict]:
    results = []
    for url in HEAD_TARGETS:
        r = p.request("HEAD", url)
        if r.get("status") in (405, 501):          # HEAD refused -> read headers via GET
            r = p.request("GET", url, max_bytes=1024)
            r["head_refused"] = True
        results.append(strip_body(r))
    return results


def planned_requests() -> list[str]:
    plan = []
    for h in HOSTS:
        plan.append(f"GET  https://{h}/robots.txt")
        plan.append(f"GET  https://{h}/sitemap.xml  (+ /sitemap_index.xml and any Sitemap: line from robots.txt, "
                    f"until one parses; first child of an index only)")
        plan.append(f"GET  https://{h}{SOFT404_PATH}   (soft-404 check)")
    for u in HEAD_TARGETS:
        plan.append(f"HEAD {u}")
    plan.append(f"GET  up to {SAMPLE_WWW} URLs listed in www's sitemap, up to {SAMPLE_OTHER} for each other host with a sitemap")
    plan.append("DNS  lookup of each host (not an HTTP request)")
    return plan


def render_report(results: dict) -> str:
    L = [f"# P0 probe report ({results['finished']})", "",
         f"requests sent: {results['requests_sent']} (cap {MAX_REQUESTS}); UA: `{UA}`", "",
         "## Per host", "",
         "| host | IPs | robots.txt | sitemap | soft-404 probe |", "|---|---|---|---|---|"]
    for h in results["hosts"]:
        rb = h["robots"]
        if "status" not in rb:
            robots = f"error: {rb.get('error', rb.get('skipped'))}"
        else:
            robots = f"{rb['status']}"
            if rb.get("looks_like_html"):
                robots += " (HTML body: soft-404?)"
            elif rb.get("parsed"):
                pr = rb["parsed"]
                robots += (f"; disallow={pr['n_disallow']}, crawl-delay={pr['crawl_delay']}, "
                           f"sitemap-lines={len(pr['sitemap_lines'])}, first: `{' / '.join(pr['first_lines'][:3])}`")
        sm = h["sitemap"]
        if sm.get("found"):
            t = next(x for x in sm["tried"] if x.get("parsed"))["parsed"]
            smt = (f"{sm['found'].replace('https://' + h['host'], '')} {t['kind']}, n={t['n']}, "
                   f"lastmod {t['lastmod_min']}..{t['lastmod_max']} (distinct={t['lastmod_distinct']}, "
                   f"all_same={t['lastmod_all_same']}); urls seen={sm['n_urls_seen']}, '/p/p/' urls={sm['slash_p_slash_p']}")
        else:
            smt = "none found (" + ", ".join(str(x.get("status", x.get("error"))) for x in sm["tried"]) + ")"
        s4 = h["soft404"]
        s4t = f"{s4.get('status', s4.get('error'))} {s4.get('content_type') or ''} -> {s4.get('location') or ''}"
        L.append(f"| {h['host']} | {', '.join(h['ips'])} | {robots} | {smt} | {s4t} |")

    L += ["", "## Sitemap URL samples (are the listed URLs alive?)", ""]
    for h in results["hosts"]:
        samples = h["sitemap"].get("samples")
        if samples:
            c = Counter(str(s.get("status", s.get("error"))) for s in samples)
            L.append(f"- **{h['host']}**: {dict(c)}")
            for s in samples:
                if s.get("status") != 200:
                    L.append(f"  - {s.get('status', s.get('error'))}: {s['url']}")

    L += ["", "## Validators and server hints (HEAD)", "",
          "| url | status | ETag | Last-Modified | Cache-Control | Server | CDN/proxy hints |", "|---|---|---|---|---|---|---|"]
    for r in results["head"]:
        L.append(f"| {r['url'][:70]} | {r.get('status', r.get('error'))} | {r.get('etag')} | {r.get('last_modified')} | "
                 f"{r.get('cache_control')} | {r.get('server')} | {r.get('via_or_cdn') or ''} |")

    ips = Counter(ip for h in results["hosts"] for ip in h["ips"])
    shared = {ip: n for ip, n in ips.items() if n > 1}
    L += ["", "## Shared IPs across the probed hosts", "", str(shared) if shared else "none"]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase J P0 read-only probe of NCCU hosts.")
    ap.add_argument("--run", action="store_true", help="actually send the requests (default: dry run)")
    args = ap.parse_args()

    if not args.run:
        print("DRY RUN -- nothing is sent. Planned requests:\n")
        for line in planned_requests():
            print("  " + line)
        print(f"\nCap: {MAX_REQUESTS} requests, >= {MIN_INTERVAL}s between requests to one host, "
              f"timeout {TIMEOUT:.0f}s, TLS verification on, redirects not followed.")
        print("Re-run with --run to send them.")
        return

    p = Prober()
    print(f"Sending requests as: {UA}\n")
    results = {"started": datetime.now().isoformat(timespec="seconds"), "hosts": []}
    for host in HOSTS:
        print(f"== {host}")
        results["hosts"].append(probe_host(p, host))
    print("== HEAD targets")
    results["head"] = probe_head_targets(p)
    results["finished"] = datetime.now().isoformat(timespec="seconds")
    results["requests_sent"] = p.count

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "p0_probe_raw.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    report = render_report(results)
    (OUT_DIR / "p0_probe_report.md").write_text(report, encoding="utf-8")
    print(f"\n{report}\nWritten to {OUT_DIR}/ ({p.count} requests)")


if __name__ == "__main__":
    main()
