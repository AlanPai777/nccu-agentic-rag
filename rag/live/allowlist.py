"""
rag/live/allowlist.py
Only *.nccu.edu.tw over http(s) may ever be fetched. It is also applied to every redirect hop, so a
page cannot bounce the fetcher to another domain. Fetched text is data, never instructions.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from rag.live.config import ALLOWED_DOMAIN


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def is_allowed(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    return host == ALLOWED_DOMAIN or host.endswith("." + ALLOWED_DOMAIN)
