"""
experiments/live_spikes/capture_chain.py
Phase J / P0 step 3 (docs/phase_j_live_fetch_plan.md §6): record the live responses of the
休學 chain once, so P1 can test fetch / compare / extraction offline against fixed files
(no network, no LLM).

Chain (mirrors what agentic_rag does for 如何辦理休學):
  A  aca 休學規定頁                       httpx GET         -> form IDs are read from the LIVE page
  B  each live-detected moltke form       httpx GET viewdetail (+ redirects) -> goFile token -> PDF download -> extract_pdf
  C  9 office staff pages                 Chromium, one page load each (same settings as fetch_office_contacts.py)

Safety (same rules as p0_probe.py): dry run by default; only the hosts below; TLS verification ON
(moltke only adds OP_LEGACY_SERVER_CONNECT); per-host pacing incl. osa's Crawl-delay of 10 s;
total httpx request cap; writes only under experiments/live_fixtures/ (gitignored).
Note: a Chromium page load also requests the page's CSS/JS/images from the same host (like a human visit);
those sub-requests are not paced.

    python experiments/live_spikes/capture_chain.py          # dry run
    python experiments/live_spikes/capture_chain.py --run
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import p0_probe as p0  # noqa: E402  (Prober: allowlist, pacing, request cap, UA, TLS rules)

ACA_PAGE = "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學"
MOLTKE = "https://moltke.nccu.edu.tw/formservice_SSO"
SNAPSHOT_FORMS = ["QP-T01-03-02", "QP-T01-03-04", "QP-T01-02-05"]        # what the 8/19 snapshot links
OFFICE_NAMES = ["註冊組", "教務長室", "住宿輔導組", "生活事務暨僑生輔導組", "原住民族學生資源中心",
                "身心健康中心", "出納組", "圖書館(各組聯絡資訊)", "國際合作事務處"]
OUT_ROOT = ROOT / "experiments" / "live_fixtures"
NAV_TIMEOUT_MS = 60_000     # plan D8
SETTLE_MS = 2000            # same as fetch_office_contacts.py
MAX_HOPS = 4


# ── pure helpers (unit-testable offline) ─────────────────────────────────────

def slug(s: str, n: int = 40) -> str:
    s = unquote(s)
    s = re.sub(r"https?://", "", s)
    s = re.sub(r"[^\w一-鿿]+", "_", s).strip("_")
    return s[:n] or "page"


def parse_viewdetail(html: str) -> dict:
    """Same extraction as rag/fetch_moltke_forms.fetch_form_page (title, unit, goFile tokens)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text()
    meta: dict = {"discontinued": ("查無此表格" in text) or ("此表格停用" in text)}
    for row in soup.select("table tr"):
        cells = row.select("td")
        pairs = [(cells[0], cells[1])] if len(cells) == 2 else \
                [(cells[0], cells[1]), (cells[2], cells[3])] if len(cells) >= 4 else []
        for k, v in pairs:
            key, val = k.get_text(" ", strip=True), v.get_text(" ", strip=True)
            if "表單名稱" in key:
                meta["form_title"] = val
            elif "承辦單位" in key:
                meta["form_unit"] = val
    links = []
    for a in soup.select('a[href="#"]'):
        m = re.search(r"goFile\('(.+?)'\)", a.get("onclick", ""))
        if m:
            prev = a.find_previous(string=True)
            links.append({"token": m.group(1), "text": a.get_text(strip=True), "file_type": prev.strip() if prev else ""})
    meta["links"] = links
    return meta


def five_digit_sets(live: str, snap: str) -> dict:
    ext = lambda t: sorted(set(re.findall(r"(?<!\d)\d{5}(?!\d)", t)))
    a, b = ext(live), ext(snap)
    return {"live": a, "snapshot": b, "only_live": sorted(set(a) - set(b)), "only_snapshot": sorted(set(b) - set(a))}


def get_follow(p: "p0.Prober", url: str, max_bytes: int = 5_000_000) -> tuple[dict, list[str]]:
    """GET, following redirects by hand so that every hop goes through the Prober's pacing and cap."""
    chain, cur = [], url
    for _ in range(MAX_HOPS):
        r = p.request("GET", cur, max_bytes=max_bytes)
        chain.append(cur)
        loc = r.get("location")
        if r.get("status") in (301, 302, 303, 307, 308) and loc:
            cur = urljoin(cur, loc)
            continue
        return r, chain
    return r, chain


# ── the capture ──────────────────────────────────────────────────────────────

def office_targets() -> list[tuple[str, str]]:
    idx = [json.loads(l) for l in open(ROOT / "output" / "office_contacts_index.jsonl", encoding="utf-8")]
    out = []
    for name in OFFICE_NAMES:
        rec = next((r for r in idx if r.get("name") == name), None)
        if rec:
            out.append((name, rec["url"]))
    return out


def snapshot_text(url: str, jsonl: Path) -> str:
    for line in open(jsonl, encoding="utf-8"):
        d = json.loads(line)
        if d.get("url") == url or unquote(d.get("url", "")) == unquote(url):
            return d.get("text", "")
    return ""


def planned() -> list[str]:
    lines = [f"A  httpx GET  {ACA_PAGE}"]
    lines += [f"B  httpx GET  {MOLTKE}/link.jsp?viewdetail={fid}  (+ redirects, then the PDF via df?<token>)   [expected from the snapshot; "
              f"the real list comes from the LIVE page]" for fid in SNAPSHOT_FORMS]
    for name, url in office_targets():
        host = urlparse(url).netloc
        gap = p0.HOST_INTERVAL.get(host, p0.MIN_INTERVAL)
        lines.append(f"C  Chromium   {name:14s} {unquote(url)[:80]}   (>= {gap:.0f}s after the previous page on {host})")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()
    if not args.run:
        print("DRY RUN -- nothing is sent. Planned:\n")
        for l in planned():
            print("  " + l)
        print(f"\nOutput would go to {OUT_ROOT}/chain_xiuxue_<date>/ (gitignored). httpx cap {p0.MAX_REQUESTS}; "
              f"osa pages are spaced >= {p0.HOST_INTERVAL['osa.nccu.edu.tw']:.0f}s apart; TLS verification on.")
        return

    from rag.preprocess import extract_html_bytes, extract_pdf, is_cloudflare_page
    from rag.agent_tools import extract_form_ids
    from rag.fetch_moltke_forms import pick_pdf_token

    out = OUT_ROOT / f"chain_xiuxue_{datetime.now():%Y-%m-%d}"
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"captured_at": datetime.now().isoformat(timespec="seconds"), "items": []}
    p = p0.Prober()
    n = 0

    def save(name: str, data: bytes) -> str:
        nonlocal n
        n += 1
        fn = f"{n:02d}_{name}"
        (out / fn).write_bytes(data)
        return fn

    print("== A: aca 休學頁")
    r, chain = get_follow(p, ACA_PAGE)
    html = r.get("_body", b"")
    text = extract_html_bytes(html, ACA_PAGE) if r.get("status") == 200 else ""
    live_ids = sorted(extract_form_ids(text))
    snap_text = snapshot_text(ACA_PAGE, ROOT / "output" / "aca" / "extracted_texts.jsonl")
    snap_ids = sorted(extract_form_ids(snap_text))
    manifest["items"].append({
        "step": "A", "url": ACA_PAGE, "status": r.get("status"), "redirects": chain[1:],
        "file": save("aca_xiuxue.html", html), "text_chars": len(text),
        "form_ids_live": live_ids, "form_ids_snapshot": snap_ids,
        "text_similarity_vs_snapshot": round(difflib.SequenceMatcher(None, text, snap_text).quick_ratio(), 3) if snap_text else None})

    print("== B: moltke forms (IDs from the LIVE page)")
    for fid in live_ids:
        url = f"{MOLTKE}/link.jsp?viewdetail={fid}"
        r, chain = get_follow(p, url)
        page = r.get("_body", b"")
        meta = parse_viewdetail(page.decode("utf-8", "replace")) if r.get("status") == 200 else {}
        item = {"step": "B", "form_id": fid, "url": url, "status": r.get("status"), "redirects": chain[1:],
                "file": save(f"moltke_{fid}_viewdetail.html", page),
                "discontinued": meta.get("discontinued"), "form_title": meta.get("form_title"), "form_unit": meta.get("form_unit")}
        pick = pick_pdf_token(meta.get("links", [])) if meta and not meta.get("discontinued") else None
        if pick:
            token, link_text = pick
            pr = p.request("GET", f"{MOLTKE}/df?{token}", max_bytes=20_000_000)
            body = pr.get("_body", b"")
            item["pdf"] = {"status": pr.get("status"), "content_type": pr.get("content_type"), "bytes": len(body),
                           "link_text": link_text, "file": save(f"moltke_{fid}.pdf", body)}
            if body[:4] == b"%PDF":
                pdf_path = out / item["pdf"]["file"]
                t = extract_pdf(pdf_path)
                item["pdf"]["text_chars"] = len(t)
                item["pdf"]["text_file"] = save(f"moltke_{fid}.pdf.txt", t.encode("utf-8"))
        manifest["items"].append(item)

    print("== C: office staff pages (Chromium, one load each)")
    from playwright.sync_api import sync_playwright
    last: dict[str, float] = {}
    idx_path = ROOT / "output" / "office_contacts_index.jsonl"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context()          # HTTPS verification stays on (default)
        for name, url in office_targets():
            host = urlparse(url).netloc
            gap = p0.HOST_INTERVAL.get(host, p0.MIN_INTERVAL) - (time.monotonic() - last.get(host, -1e9))
            if gap > 0:
                time.sleep(gap)
            page = ctx.new_page()
            failed: list[str] = []
            page.on("requestfailed", lambda rq, f=failed: f.append(f"{rq.url[:70]} :: {rq.failure}"))
            t0 = time.monotonic()
            item: dict = {"step": "C", "office": name, "url": url}
            try:
                resp = page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="load")
                page.wait_for_timeout(SETTLE_MS)
                rendered = page.content().encode("utf-8")
                live_text = extract_html_bytes(rendered, url)
                snap = snapshot_text(url, idx_path)
                item.update({"status": resp.status if resp else None, "cloudflare_page": is_cloudflare_page(rendered),
                             "file": save(f"office_{slug(name)}.html", rendered), "text_chars": len(live_text),
                             "extensions": five_digit_sets(live_text, snap)})
            except Exception as e:
                item["error"] = f"{type(e).__name__}: {e}"
            item["ms"] = round((time.monotonic() - t0) * 1000)
            item["failed_subrequests"] = failed[:3]
            last[host] = time.monotonic()
            page.close()
            manifest["items"].append(item)
            print(f"  {name:14s} status={item.get('status', item.get('error'))}  {item['ms']} ms", flush=True)
        browser.close()

    manifest["httpx_requests"] = p.count
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {n} files + manifest.json to {out}\n")
    A = manifest["items"][0]
    print(f"form IDs on the live page : {A['form_ids_live']}")
    print(f"form IDs in the snapshot  : {A['form_ids_snapshot']}   -> same set: {A['form_ids_live'] == A['form_ids_snapshot']}")
    for it in manifest["items"]:
        if it["step"] == "C":
            e = it.get("extensions") or {}
            print(f"  {it['office']:14s} extensions changed vs index: +{e.get('only_live')} -{e.get('only_snapshot')}")


if __name__ == "__main__":
    main()
