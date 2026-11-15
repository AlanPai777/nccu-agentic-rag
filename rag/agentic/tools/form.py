"""
rag/agentic/tools/form.py
get_form_tool: fetch a known form ID's full content.
"""

from __future__ import annotations

import time
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from langfuse import observe

from rag.agent_tools import get_form as _get_form_raw
from rag.live import events
from rag.live.config import live_enabled
from rag.live.forms import link_url_for
from rag.live.hook import apply_form
from rag.live.prefetch import get_store


def _download_line(form_id: str | None) -> str:
    """The official download link as its own line, so an answer's 表單下載 link is this one and not the url of some other page that carries
    a copy of the same form (a department's own PDF, say). Data-level: it is the same for every form. Only in the live-marker branch, after the
    marker line (ledger.parse_markers reads the marker from the header): the text without live keeps its old exact shape (plan: live=None is byte-identical)."""
    return f"\n下載連結：{link_url_for(form_id)}" if form_id else ""


def _tool_text(f: dict, form_id: str | None = None) -> str:
    if "error" in f:
        return f"get_form 失敗: {f['error']}"
    dl = _download_line(form_id)
    if f.get("live_marker"):       # live only; marker in the header, body after 全文：
        note = "（官網顯示此表單已停用，請勿引用或提供下載）" if f.get("discontinued") else ""
        return f"get_form 取得表單 {f.get('form_title','')}{note}\n{f['live_marker']}{dl}\n\n全文：\n{f.get('text','')}"
    return f"get_form 取得表單 {f.get('form_title','')}\n\n{f.get('text','')}"


@observe(as_type="tool", name="get_form_tool")
def fetch_form_for_agent(form_id: str, live: bool | None = None) -> str:
    """What get_form_tool returns, as a plain function: resource_node fetches forms through it directly (it has no tool-call state to inject),
    passing the question's own `live` choice (AgentState["live"]; None = LIVE_FETCH alone decides). Adds a row to the current progress group
    (events.group), if its caller opened one."""
    g = events.current_group()
    link = link_url_for(form_id)
    rid = g.row("start", url=link, title=form_id, state="pending", kind="form") if (g and live_enabled(live)) else None
    t0 = time.monotonic()
    # With LIVE_PREFETCH on, the snapshot lookup and the live fetch may already have been done (or be under way) by the prefetch.
    # Otherwise these two lines do exactly what they always did.
    store = get_store()
    snap = store.form_snapshot(form_id, lambda: _get_form_raw(form_id))
    f = store.form_live(form_id, lambda: apply_form(form_id, snap, live))
    if g and "error" not in f:
        g.row("done", rid=rid, url=link, title=f.get("form_title") or form_id, state=f.get("live_state") or "snapshot", marker=f.get("live_marker"),
              seconds=time.monotonic() - t0, kind="form")
    return _tool_text(f, form_id)


@tool
def get_form_tool(form_id: str, state: Annotated[dict, InjectedState]) -> str:
    """取得已知表單編號的完整內容。當頁面提到表單編號、但你不確定頁面本身的敘述是否已涵蓋完整細節時使用——表單常包含頁面沒寫清楚的細節。"""
    with events.group("form", form_id, refine=True):               # progress events for the front end; the returned text is unchanged
        return fetch_form_for_agent(form_id, state.get("live"))
