"""
server.py
FastAPI service exposing agentic_rag.py's graph over SSE to
CourseLangChain-frontend's AssistantChat.vue page (VITE_ASSISTANT_API_BASE).

docs/phase_i_assistant_api_design.md is the design record for why this
shape -- filtering stream_mode="messages" by langgraph_node instead of
CourseLangChain/app.py's "no tool_calls = final answer" heuristic -- was
needed: agentic_rag.py's graph has several nodes that call an LLM, and only
synthesis_node's output is meant to reach the user.

    python server.py
    uvicorn server:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.memory import InMemorySaver
from langfuse import observe

from agentic_rag import build_graph, initial_state
from rag.agentic.compaction import compact_previous_turn
from rag.agentic.nodes.self_eval import _SELF_EVAL_MAX_TURN
from rag.live import config as live_config
from rag.live.sources import build_sources

load_dotenv()  # rag/agentic/nodes/loop.py already does this on import; kept for direct runs

log = logging.getLogger("rag.server")

app = FastAPI()

# The assistant page is a deliberately different host from the course-
# scheduling frontend (config/assistant.ts: "不同 host，所以不走 /api 的
# dev proxy") -- CORS is required here even though CourseLangChain's app.py
# doesn't need it (that one stays same-origin behind an nginx /api proxy).
_frontend_origins = [
    o.strip()
    for o in os.environ.get("ASSISTANT_FRONTEND_ORIGIN", "http://localhost:3001").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# InMemorySaver must be a single instance shared across every request --
# it's the in-process store LangGraph's checkpointer reads/writes, so a
# per-request instance would never see a previous turn's state.
_graph = build_graph(checkpointer=InMemorySaver())

# SSE heartbeat interval, same rationale as CourseLangChain/app.py: the
# reverse proxy's read-timeout tracks silence between writes, not total
# request length, and inference can stay quiet for minutes at a time.
_HEARTBEAT_SEC = 15
_STREAM_DONE = object()  # sentinel distinct from a legitimate None chunk

# The status lines are the plain-text "說明行" of the front end's progress list (rag/live/events.py draws the action blocks: every tool
# action and the form/contact nodes already show up there with real pages, so the lines below only say what the blocks cannot -- what kind
# of question this is, where the search is narrowed to, what a page mentioned, that the data is enough). Nodes with nothing to add return
# None and send no line.
_QUERY_TYPE_LABEL = {
    "procedure": "辦理流程", "contact": "聯絡資訊", "resource": "表單與連結", "knowledge": "一般資訊", "compound": "多個問題",
}
_DONE_WORDS = {"夠了", "够了", "足夠", "足够", "完成", "done"}

# Reuses the exact marker format rag/agentic/tools/page.py's get_page_tool
# already stamps onto its own return value when it detects a form/office
# reference (rag/agentic/logic/{form_extraction,office_detection}.py) --
# read-only here, purely for display; doesn't change what the agent does
# with that text.
_FORM_MARKER_RE = re.compile(r"\[偵測到表單編號: ([^\]]+)\]")
_OFFICE_MARKER_RE = re.compile(r"\[偵測到辦公室: ([^\]]+)\]")
# domain_router_node's message (rag/agentic/nodes/loop.py): "1. aca（描述）— …" is its first candidate.
_FIRST_SUBDOMAIN_RE = re.compile(r"^1\. ([A-Za-z0-9.\-]+)（", re.M)
_MAX_LINE = 80


def _short(text: str) -> str:
    text = text.strip().split("\n")[0].strip()
    return text if len(text) <= _MAX_LINE else text[:_MAX_LINE - 1] + "…"


def _status_text(node_name: str, delta: dict) -> str | None:
    """One node update -> one plain-text status line for the progress list, or None when the node has nothing to add.

    Prefers text a node already generated for its own purposes (rewrite_node's `rewritten`, agent_node's reply text, self_eval's note) --
    "one LLM output, two consumers" (phase_g_brainstorming.txt) -- and otherwise composes a sentence from real data in `delta`
    (the question type, the narrowed site, the forms/offices a page mentioned). No extra LLM call (P8.7b: model-written narration, B5,
    is deliberately not done yet). None of this changes what any node returns to the graph."""
    if node_name == "plan_node":
        label = _QUERY_TYPE_LABEL.get(str(delta.get("query_type") or "").lower())
        return f"判斷問題類型：{label}" if label else "判斷問題類型"
    if node_name == "multi_sub_query_node":
        return "拆解成多個問題，逐一查詢"
    if node_name == "rewrite_node" and delta.get("rewritten"):
        return f"搜尋詞：{_short(delta['rewritten'])}"
    if node_name == "domain_router_node":
        msgs = delta.get("messages") or []
        if not msgs:
            return None
        text = str(msgs[-1].content)
        hit = _FIRST_SUBDOMAIN_RE.search(text)
        if hit:
            from rag.live.site_names import site_name
            host = hit.group(1) if "." in hit.group(1) else f"{hit.group(1)}.nccu.edu.tw"
            return f"縮小搜尋範圍：{site_name(host)}"
        return "不限定單一網站，搜尋全部網站" if "無（" in text else None
    if node_name == "agent_node":
        # agent_node's docstring notes resp.content is generated as a side effect of the bind_tools() call and then discarded -- it is
        # already in delta["messages"]. Empty when the model replied with tool_calls only (then the action blocks speak for it).
        msgs = delta.get("messages") or []
        text = str(getattr(msgs[-1], "content", "") or "").strip() if msgs else ""
        if not text:
            return None
        return "資料已足夠，整理答案" if text.strip("。.!！ ") in _DONE_WORDS else _short(text)
    if node_name == "tools":
        # The tool actions are drawn as blocks; what a block cannot show is what the page MENTIONED.
        hits = []
        for m in delta.get("messages") or []:
            content = str(getattr(m, "content", "") or "")
            form_hit, office_hit = _FORM_MARKER_RE.search(content), _OFFICE_MARKER_RE.search(content)
            if form_hit:
                hits.append(f"表單 {form_hit.group(1)}")
            if office_hit:
                hits.append(f"辦公室 {office_hit.group(1)}")
        return f"頁面提到：{'；'.join(hits)}" if hits else None
    if node_name == "resource_node":
        msgs = delta.get("messages") or []
        hit = _OFFICE_MARKER_RE.search(str(getattr(msgs[-1], "content", "") or "")) if msgs else None
        return f"表單提到辦公室：{hit.group(1)}" if hit else None
    if node_name == "self_eval_node" and delta.get("self_eval_note"):
        # self_eval_node's three failure branches (Stage 1 checklist, 情況A, 情況B) don't all populate `messages` -- 情況B only sets
        # self_eval_note, the one signal common to all three, so it is the thing to key off.
        msgs = delta.get("messages") or []
        return _short(str(msgs[-1].content) if msgs else delta["self_eval_note"])
    return None                                           # contact_node, synthesis_node, …: their blocks / the answer speak for them


def _is_retry_signal(node_name: str, delta: dict, current_turn: int) -> bool:
    """True exactly when self_eval_node just rejected the draft synthesis_node
    answer AND the graph is actually about to retry -- the caller should then
    tell the frontend to file that draft into the thinking log and clear the
    answer area before the next synthesis_node run starts streaming its
    replacement.

    current_turn < _SELF_EVAL_MAX_TURN mirrors _after_self_eval's own ceiling
    check (rag/agentic/nodes/self_eval.py) exactly: on the terminal turn,
    self_eval_node can still reject (self_eval_note truthy) but
    _after_self_eval routes to "end" instead of back to rewrite_node/
    plan_node, so no replacement synthesis is ever coming. Without this
    guard, that terminal rejection still emitted "reset", wiping the last
    (possibly perfectly good) streamed answer with nothing left to refill
    it -- confirmed via a live repro against "資科系系主任" running all the
    way to turn 20 and leaving the frontend blank."""
    return (
        node_name == "self_eval_node"
        and bool(delta.get("self_eval_note"))
        and current_turn < _SELF_EVAL_MAX_TURN
    )


def _thread_config(session_id: str | None) -> dict:
    # No session_id -> one-off id, same "ephemeral = no memory" fallback
    # CourseLangChain/main.py's _base_config uses (a checkpointer-backed
    # graph raises without SOME thread_id).
    return {"configurable": {"thread_id": session_id or f"ephemeral-{os.urandom(8).hex()}"}}


def _live_available() -> bool:
    """False when the operator turned live off for the whole server (LIVE_FETCH=off, or anything unrecognised): the front end's switch is then
    greyed out and every question runs from the snapshot."""
    return os.environ.get("LIVE_FETCH", "").strip().lower() in ("", "on")


def _effective_live(param: str | None) -> bool:
    """The "查現場" choice for one question: /ask?live=on|off; the kill switch beats it. With no parameter (curl, an old client) LIVE_FETCH alone
    decides -- unset means off, so nothing reaches nccu.edu.tw by accident; the front end's switch starts "on" and always sends the parameter.
    Always an explicit bool, so a question that turns live off still records the pages it read (rag/live/hook.py)."""
    if not _live_available():
        return False
    choice = (param or "").strip().lower()
    if choice in ("on", "off"):
        return choice == "on"
    return live_config.live_enabled(None)


def _slow_text(seconds: float, live: bool) -> str:
    """The waiting notice for a threshold (rag/live/config.py SLOW_WARN_SECONDS, LIVE_SLOW_WARN_SECONDS); warn only, never abort."""
    waited = f"{seconds / 60:g} 分鐘" if seconds >= 60 else f"{seconds:g} 秒"
    if seconds >= 300:
        if live:
            return f"已等待 {waited}，官網可能回應很慢或沒有回應。你可以按停止，之後再問一次，或關閉「查現場」改用資料庫的資料。"
        return f"已等待 {waited}，系統回應很慢。你可以按停止後再問一次。"
    if live:
        return f"已等待 {waited}，比平常久一些，仍在向官網確認資料，請再稍候。"
    return f"已等待 {waited}，比平常久一些，仍在處理，請再稍候。"


async def _put_sources(config: dict, queue: asyncio.Queue) -> None:
    """After the graph finished (self_eval may have sent synthesis round again, so only now is the answer final): the sources the answer
    was written from, built from the ledger markers in the thread's messages. A failure here must not spoil an answer that already streamed."""
    try:
        values = (await _graph.aget_state(config)).values
        await queue.put(build_sources(values.get("messages") or [], bool(values.get("live"))))
    except Exception as e:  # noqa: BLE001
        log.warning("sources event not sent: %s: %s", type(e).__name__, e)


@observe(name="server.pump")
async def _pump(
    question: str, subdomain_hint: str | None, session_id: str | None, config: dict, queue: asyncio.Queue,
    live: bool | None = None,
) -> None:
    """Run one turn, push every SSE-worthy event into the queue.

    Exceptions are queued rather than handled here -- the SSE consumer
    (_generate) is the one place that knows how to format them for the
    frontend's `error` field, matching CourseLangChain/app.py's split.
    """
    from langfuse import get_client
    get_client().update_current_span(metadata={"session_id": session_id, "subdomain_hint": subdomain_hint})
    current_turn = 0  # tracks state["turn"] as rewrite_node advances it, so
    # _is_retry_signal can mirror _after_self_eval's own ceiling check below
    try:
        if session_id:
            # Collapse the PREVIOUS turn's raw scratch before this new one
            # starts -- an ephemeral (session_id-less) thread is always
            # fresh, so skip the wasted checkpoint read for those.
            compact_previous_turn(_graph, config)
        state = initial_state(question, subdomain_hint, live)
        # Tells the front end what this question really runs with (the operator's switch may have overridden its request).
        await queue.put({"type": "meta", "live": live_config.live_enabled(live), "live_available": _live_available(),
                         "snapshot_date": live_config.SNAPSHOT_ASOF})
        async for stream_mode, payload in _graph.astream(
            state, config=config, stream_mode=["updates", "messages", "custom"]
        ):
            if stream_mode == "messages":
                chunk, metadata = payload
                # isinstance check matters here, not just langgraph_node --
                # synthesis_node's return value itself adds a *complete*
                # AIMessage to state["messages"] (Item E, so the next turn
                # can read the prior conclusion), and stream_mode="messages"
                # surfaces that addition too, not just live token deltas.
                # Without this check the full text streams once as genuine
                # AIMessageChunk deltas, then AGAIN whole as that plain
                # AIMessage -- confirmed via a live repro against "如何辦理
                # 休學" (small chunks throughout, one final chunk containing
                # the entire answer a second time).
                if (
                    isinstance(chunk, AIMessageChunk)
                    and metadata.get("langgraph_node") == "synthesis_node"
                    and chunk.content
                ):
                    await queue.put({"data": chunk.content})
            elif stream_mode == "custom":
                # Progress events from rag/live/events.py (tools and nodes: {"type":"step",...}); forwarded as they come. A front end
                # that does not know a "type" ignores it.
                if isinstance(payload, dict) and payload.get("type"):
                    await queue.put(payload)
            elif stream_mode == "updates":
                for node_name, delta in payload.items():
                    delta = delta or {}
                    if node_name == "rewrite_node" and "turn" in delta:
                        current_turn = delta["turn"]
                    # Reset before the status line explaining why -- the
                    # frontend files the just-cleared draft into its
                    # thinking log labeled with that reason, so ordering
                    # them clear-then-explain reads correctly top to bottom.
                    if _is_retry_signal(node_name, delta, current_turn):
                        await queue.put({"type": "reset"})
                    # P8: the 【資料狀態】 footer is no longer streamed as answer text -- the same information goes out as the
                    # "sources" event below. The footer stays in state["answer"] (self_eval's disclosure check, the CLI and eval read it).
                    text = _status_text(node_name, delta)
                    if text:
                        await queue.put({"type": "status", "text": text})
        await _put_sources(config, queue)
    except Exception as e:  # noqa: BLE001 -- formatted for the user by _generate
        await queue.put(e)
    finally:
        await queue.put(_STREAM_DONE)


async def _generate(question: str, subdomain_hint: str | None, session_id: str | None, live: bool | None = None):
    config = _thread_config(session_id)
    queue: asyncio.Queue = asyncio.Queue()
    pump = asyncio.create_task(_pump(question, subdomain_hint, session_id, config, queue, live))
    started = time.monotonic()
    pending_warnings = list(live_config.SLOW_WARN_SECONDS)       # each threshold fires once, and only while no answer text has appeared
    answering = False

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SEC)
            except asyncio.TimeoutError:
                item = None
                yield ": keepalive\n\n"
            if isinstance(item, dict) and "data" in item:
                answering = True
            while pending_warnings and not answering and time.monotonic() - started >= pending_warnings[0]:
                secs = pending_warnings.pop(0)
                yield f"data: {json.dumps({'type': 'slow', 'seconds': secs, 'text': _slow_text(secs, live_config.live_enabled(live))})}\n\n"
            if item is None:
                continue

            if item is _STREAM_DONE:
                break
            if isinstance(item, Exception):
                msg = f"抱歉，系統發生錯誤，暫時無法處理您的要求。（{type(item).__name__}）"
                yield f"data: {json.dumps({'data': msg, 'error': str(item)})}\n\n"
                continue
            yield f"data: {json.dumps(item)}\n\n"
    finally:
        # A closed SSE connection (tab closed mid-turn) should stop the
        # graph too, not keep burning turns nobody is listening to.
        pump.cancel()

    yield f"data: {json.dumps({'data': 'SPECIAL_END_TOKEN'})}\n\n"


@app.get("/config")
async def get_config():
    """What the front end needs before the first question: whether its "查現場" switch can work at all (the operator's LIVE_FETCH=off kill
    switch greys it out) and the date of the snapshot ("資料庫") the answers fall back on."""
    return {"live_available": _live_available(), "snapshot_date": live_config.SNAPSHOT_ASOF}


@app.get("/ask")
async def ask(question: str, session_id: str | None = None, subdomain: str | None = None, live: str | None = None):
    """SSE chat endpoint. `session_id` ties multi-turn context to a
    LangGraph thread_id; omit it for a one-off, memory-less question.
    `live=on|off`: whether this question confirms pages with nccu.edu.tw while it answers; omitted = LIVE_FETCH decides (unset: off)."""
    return StreamingResponse(
        _generate(question, subdomain, session_id, _effective_live(live)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
