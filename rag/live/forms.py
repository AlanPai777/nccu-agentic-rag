"""
rag/live/forms.py
Live retrieval of a moltke form.

The 5-request chain (link.jsp -> login.formservice -> viewDetail.formservice -> viewFormDetail.jsp -> df?<token>)
is held together by a server-side session: viewFormDetail.jsp carries NO form id in its URL, the cookie set by the
first redirect decides which form you get. So every form uses its OWN client (own cookie jar). Forms fetched
side by side can never see each other's session.

Not OCR'd: an image-only PDF yields no text and is reported as a failure (caller falls back to the snapshot).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from rag.live import config
from rag.live.cache import CacheRow
from rag.live.fetcher import Fetcher

MOLTKE = "https://moltke.nccu.edu.tw/formservice_SSO"
MOLTKE_HOST = "moltke.nccu.edu.tw"


@dataclass
class FormLive:
    form_id: str
    link_url: str
    ok: bool = False
    discontinued: bool = False
    title: str = ""
    unit: str = ""
    text: str = ""
    pdf_path: str = ""
    pdf_hash: str = ""
    error: str = ""            # fetch error code from Fetcher, or no_pdf|not_pdf|empty_pdf
    detail: str = ""
    elapsed: float = 0.0
    requests: int = 0
    fetched_at: float = 0.0
    from_cache: bool = False


def parse_viewdetail(html: str) -> dict:
    """Same extraction as rag/fetch_moltke_forms.fetch_form_page: title, unit, goFile tokens, discontinued flag."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text()
    meta: dict = {"discontinued": ("查無此表格" in text) or ("此表格停用" in text), "links": []}
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
    for a in soup.select('a[href="#"]'):
        m = re.search(r"goFile\('(.+?)'\)", a.get("onclick", ""))
        if m:
            prev = a.find_previous(string=True)
            meta["links"].append({"token": m.group(1), "text": a.get_text(strip=True),
                                  "file_type": prev.strip() if prev else ""})
    return meta


def link_url_for(form_id: str) -> str:
    return f"{MOLTKE}/link.jsp?viewdetail={form_id}"


def _pack(f: FormLive) -> str:
    return json.dumps({"title": f.title, "unit": f.unit, "text": f.text, "discontinued": f.discontinued}, ensure_ascii=False)


def fetch_form(form_id: str, fetcher: Fetcher, pdf_dir: Path | None = None) -> FormLive:
    from rag.fetch_moltke_forms import pick_pdf_token
    from rag.preprocess import extract_pdf
    link = link_url_for(form_id)
    f = FormLive(form_id, link)
    t0 = time.monotonic()

    if fetcher.cache:
        row = fetcher.cache.get(link)
        if row:
            d = json.loads(row.text)
            return FormLive(form_id, link, True, d["discontinued"], d["title"], d["unit"], d["text"], row.pdf_path or "",
                            row.raw_hash, fetched_at=row.fetched_at, from_cache=True)

    client = fetcher.new_session(MOLTKE_HOST)         # private cookie jar for this form
    try:
        page = fetcher.fetch(link, kind="form", use_cache=False, client=client, raw=True)
        f.requests = 1 + len(page.redirects)
        if not page.ok:
            f.error, f.detail = page.error, page.detail
            return f
        meta = parse_viewdetail(page.body.decode("utf-8", "replace"))
        f.title, f.unit = meta.get("form_title", ""), meta.get("form_unit", "")
        if meta["discontinued"]:
            f.ok, f.discontinued = True, True
            f.fetched_at = page.fetched_at
            return f
        pick = pick_pdf_token(meta["links"])
        if not pick:
            f.error, f.detail = "no_pdf", "no PDF link on the form page"
            return f
        token, _ = pick
        pdf = fetcher.fetch(f"{MOLTKE}/df?{token}", kind="pdf", use_cache=False, client=client, raw=True)
        f.requests += 1 + len(pdf.redirects)
        if not pdf.ok:
            f.error, f.detail = pdf.error, pdf.detail
            return f
        if pdf.body[:4] != b"%PDF":
            f.error, f.detail = "not_pdf", f"got {len(pdf.body)} bytes that are not a PDF"
            return f
        pdf_dir = pdf_dir or (config.CACHE_DIR / "pdf")
        pdf_dir.mkdir(parents=True, exist_ok=True)
        f.pdf_hash = hashlib.sha256(pdf.body).hexdigest()[:16]
        path = pdf_dir / f"{f.pdf_hash}.pdf"
        path.write_bytes(pdf.body)
        f.pdf_path = str(path)
        f.text = extract_pdf(path)
        if not f.text.strip():
            f.error, f.detail = "empty_pdf", "no text layer (image-only PDF; live path does not OCR)"
            return f
        f.ok, f.fetched_at = True, pdf.fetched_at
        return f
    finally:
        client.close()
        f.elapsed = time.monotonic() - t0
        if f.ok and fetcher.cache:
            fetcher.cache.put(CacheRow(link, "form", link, f.fetched_at, 200, f.pdf_hash, f.pdf_hash, _pack(f), f.pdf_path or None, False))
