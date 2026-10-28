"""
rag/live/extract.py
HTML bytes -> page text, with the same extractor that built the snapshot (rag/preprocess.py), so live-vs-snapshot
differences are real changes and not extractor drift. Shared by the httpx fetcher and the Chromium renderer.
"""

from __future__ import annotations

from pathlib import Path


def html_to_text(body: bytes, url: str) -> tuple[str, str]:
    """Returns (text, error). Error is "" on success, else "cloudflare" (challenge page) or "empty" (nothing
    extracted)."""
    from rag.preprocess import extract_html_bytes, is_cloudflare_page
    if is_cloudflare_page(body):
        return "", "cloudflare"
    text = extract_html_bytes(body, url)
    # With no usable content the extractor falls back to a title made from the URL's last path segment, or to a
    # Joomla placeholder. That is "nothing extracted", not content.
    if text.strip() == Path(url.rstrip("/").split("/")[-1]).stem or "Blank Component" in text:
        text = ""
    return (text, "") if text.strip() else ("", "empty")
