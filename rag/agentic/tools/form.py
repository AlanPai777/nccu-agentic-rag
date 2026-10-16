"""
rag/agentic/tools/form.py
get_form_tool: fetch a known form ID's full content (Migration Step 3).
Ported directly from rag/agentic_main.py.
"""

from __future__ import annotations

from langchain_core.tools import tool
from langfuse import observe

from rag.agent_tools import get_form as _get_form_raw
from rag.live.hook import apply_form
from rag.live.prefetch import get_store


@tool
@observe(as_type="tool", name="get_form_tool")
def get_form_tool(form_id: str) -> str:
    """取得已知表單編號的完整內容。當頁面提到表單編號、但你不確定頁面本身的敘述是否已涵蓋完整細節時使用——表單常包含頁面沒寫清楚的細節。"""
    # With LIVE_PREFETCH on, the snapshot lookup and the live fetch may already have been done (or be under way) by the prefetch;
    # otherwise these two lines do exactly what they always did.
    store = get_store()
    snap = store.form_snapshot(form_id, lambda: _get_form_raw(form_id))
    f = store.form_live(form_id, lambda: apply_form(form_id, snap))
    if "error" in f:
        return f"get_form 失敗: {f['error']}"
    if f.get("live_marker"):       # LIVE_FETCH=on only; marker in the header, body after 全文：
        note = "（官網顯示此表單已停用，請勿引用或提供下載）" if f.get("discontinued") else ""
        return f"get_form 取得表單 {f.get('form_title','')}{note}\n{f['live_marker']}\n\n全文：\n{f.get('text','')}"
    return f"get_form 取得表單 {f.get('form_title','')}\n\n{f.get('text','')}"
