"""
rag/agentic/tools/page.py
get_page_tool / extract_links_tool: fetch a known URL's full content, or the links it references.
"""

from __future__ import annotations

import time
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from langfuse import observe

from rag.agent_tools import (
    get_page as _get_page_raw,
    extract_form_ids,
    links_from_text,
)
from rag.agentic.logic.office_detection import _detect_offices
from rag.live import events
from rag.live.config import live_enabled
from rag.live.hook import apply_page
from rag.live.prefetch import maybe_start as start_prefetch


@tool
@observe(as_type="tool", name="get_page_tool")
def get_page_tool(url: str, state: Annotated[dict, InjectedState]) -> str:
    """取得已知URL的完整頁面內容。只在已有明確URL時呼叫。"""
    snapshot = _get_page_raw(url, subdomain=state.get("subdomain_hint"))
    live = state.get("live")            # this question's choice (None = LIVE_FETCH alone decides)
    title = "" if "error" in snapshot else snapshot.get("title", "")
    with events.group("page", title or events.url_title(url)) as g:     # progress events for the front end; the returned text is unchanged
        start_prefetch(url, snapshot, live=live)   # no-op unless live and LIVE_PREFETCH=on; runs in the background, before the live check
        rid = g.row("start", url=url, title=title, state="pending") if live_enabled(live) else None
        t0 = time.monotonic()
        p = apply_page(url, snapshot, live)
        if "error" in p:
            return f"get_page 失敗: {p['error']}"
        g.row("done", rid=rid, url=p.get("url") or url, title=p.get("title") or title, state=p.get("live_state") or "snapshot",
              marker=p.get("live_marker"), seconds=time.monotonic() - t0)
        text = p.get("text", "")
        header = f"get_page 取得 {len(text)} 字，標題: {p.get('title','')}，subdomain: {p.get('subdomain','')}"
        if p.get("live_marker"):       # live (or an explicit live=False): the ledger line sits in the header, never in the page text
            header += "\n" + p["live_marker"]
        form_ids = sorted(extract_form_ids(text))
        if form_ids:
            header += f"\n[偵測到表單編號: {', '.join(form_ids)}]"
        else:
            # Only check here when there's no form -- when a form IS present,
            # resource_node scans the form's own (freshly-fetched) text,
            # not this page's narrative text.
            # Pure CONTACT-type queries never surface a form marker at all
            # (e.g. "出納組電話幾號"), so without this branch contact_node was
            # unreachable except as a side effect of resource_node -- there was
            # no path from a plain office-name page straight into contact_node.
            offices = _detect_offices(text)
            if offices:
                header += f"\n[偵測到辦公室: {', '.join(offices)}]"
        return f"{header}\n\n全文：\n{text}"


@tool
@observe(as_type="tool", name="extract_links_tool")
def extract_links_tool(url: str, state: Annotated[dict, InjectedState]) -> str:
    """取得頁面正文明確提到的其他連結。當目前頁面內容不足以回答問題、但內文提到其他相關文件或頁面時使用。"""
    # The links come from the page as the live check left it (the snapshot when nothing changed or the live fetch failed, the live text
    # when the page changed), not from the snapshot alone. get_page_tool just read this URL, so with LIVE_FETCH=on the side cache normally
    # answers without a new request. With LIVE_FETCH=off apply_page returns the snapshot page untouched: same links as before.
    snapshot = _get_page_raw(url, subdomain=state.get("subdomain_hint"))
    live = state.get("live")
    title = "" if "error" in snapshot else snapshot.get("title", "")
    with events.group("links", title or events.url_title(url)) as g:    # progress events for the front end; the returned text is unchanged
        rid = g.row("start", url=url, title=title, state="pending") if live_enabled(live) else None
        t0 = time.monotonic()
        page = apply_page(url, snapshot, live)
        if "error" not in page:
            g.row("done", rid=rid, url=page.get("url") or url, title=page.get("title") or title, state=page.get("live_state") or "snapshot",
                  marker=page.get("live_marker"), seconds=time.monotonic() - t0)
    links = [] if "error" in page else links_from_text(page.get("text", ""))
    if not links:
        return "extract_links 找到 0 個連結"
    return "extract_links 找到:\n" + "\n".join(f"- {l['label']}: {l['url']}" for l in links[:10])
