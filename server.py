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

# node_name -> static status phrase, for nodes with no natural-language
# output of their own to reuse (see _status_text below for the nodes that do).
# Also the fallback for agent_node/tools/resource_node/contact_node below when
# the richer per-call text they now try first isn't available for that call.
_STATIC_STATUS = {
    "plan_node": "正在判斷問題類型…",
    "agent_node": "正在決定下一步…",
    "tools": "正在查詢政大官方資料…",
    "resource_node": "正在讀取表單…",
    "contact_node": "正在查詢辦公室聯絡資訊…",
    "multi_sub_query_node": "正在拆解問題…",
}

# TOOLS' registered names (rag/agentic/tools/__init__.py) -> a readable phrase,
# for the "tools" node's ToolMessage.name (set by langgraph's prebuilt ToolNode).
_TOOL_STATUS = {
    "search_texts": "正在搜尋頁面全文索引…",
    "grep_texts_tool": "正在用關鍵字比對頁面…",
    "get_page_tool": "正在讀取頁面全文…",
    "extract_links_tool": "正在展開頁面內的相關連結…",
    "get_form_tool": "正在讀取表單…",
}

# Reuses the exact marker format rag/agentic/tools/page.py's get_page_tool
# already stamps onto its own return value when it detects a form/office
# reference (rag/agentic/logic/{form_extraction,office_detection}.py) --
# read-only here, purely for display; doesn't change what the agent does
# with that text.
_FORM_MARKER_RE = re.compile(r"\[偵測到表單編號: ([^\]]+)\]")
_OFFICE_MARKER_RE = re.compile(r"\[偵測到辦公室: ([^\]]+)\]")
# contact_node (rag/agentic/nodes/contact.py) builds its own header prose
# instead of the marker above, so it needs its own extraction pattern.
_CONTACT_OFFICES_RE = re.compile(r"個辦公室（([^）]+)）")


def _status_text(node_name: str, delta: dict) -> str | None:
    """One node update -> one human-readable status line.

    Prefers text the node already generated for its own purposes over a
    static label (phase_g_brainstorming.txt's "one LLM output, two
    consumers" idea) -- rewrite_node's `rewritten` and domain_router_node/
    self_eval_node's injected messages are natural-language LLM output
    already, no separate summarizer call needed. agent_node/tools/
    resource_node/contact_node below extend the same idea to data that was
    already being returned in `delta` but simply never read for status
    purposes -- none of this changes what any node returns to the graph.
    """
    if node_name == "rewrite_node" and delta.get("rewritten"):
        return f"正在搜尋：{delta['rewritten']}"
    if node_name == "domain_router_node":
        msgs = delta.get("messages") or []
        if msgs:
            return str(msgs[-1].content).split("\n")[0]
    if node_name == "self_eval_node" and delta.get("self_eval_note"):
        # self_eval_node's three failure branches (Stage 1 checklist,
        # 情況A, 情況B) don't all populate `messages` -- 情況B (routes back
        # to plan_node, which never reads `messages` at all) only sets
        # self_eval_note. That field is the one signal common to all three,
        # so it's the correct thing to key off, not `messages`'s presence.
        msgs = delta.get("messages") or []
        text = str(msgs[-1].content) if msgs else delta["self_eval_note"]
        return text.split("\n")[0]
    if node_name == "agent_node":
        # agent_node's docstring notes resp.content is generated as a side
        # effect of the bind_tools() call and then discarded -- it's already
        # in `delta["messages"]`, just never read until now. Empty when the
        # model replied with tool_calls only and no text (falls through to
        # the static label below in that case).
        msgs = delta.get("messages") or []
        if msgs:
            text = str(getattr(msgs[-1], "content", "") or "").strip()
            if text:
                return text.split("\n")[0]
    if node_name == "tools":
        msgs = delta.get("messages") or []
        names = [getattr(m, "name", None) for m in msgs if getattr(m, "name", None)]
        if names:
            base = "、".join(_TOOL_STATUS.get(n, n) for n in dict.fromkeys(names))
            hits = []
            for m in msgs:
                content = str(getattr(m, "content", "") or "")
                form_hit = _FORM_MARKER_RE.search(content)
                office_hit = _OFFICE_MARKER_RE.search(content)
                if form_hit:
                    hits.append(f"表單:{form_hit.group(1)}")
                if office_hit:
                    hits.append(f"辦公室:{office_hit.group(1)}")
            return base + (f"(偵測到{'、'.join(hits)})" if hits else "")
    if node_name == "resource_node":
        # The combined text resource_node returns doesn't itself name which
        # form_id(s) it fetched (that's a local variable, never part of the
        # returned message) -- only the office marker survives into `delta`
        # when station_roles matched. Falls back to the static label when
        # it didn't, same as before this change.
        msgs = delta.get("messages") or []
        if msgs:
            hit = _OFFICE_MARKER_RE.search(str(getattr(msgs[-1], "content", "") or ""))
            if hit:
                return f"正在讀取表單全文,偵測到辦公室:{hit.group(1)}"
    if node_name == "contact_node":
        msgs = delta.get("messages") or []
        if msgs:
            hit = _CONTACT_OFFICES_RE.search(str(getattr(msgs[-1], "content", "") or ""))
            if hit:
                return f"正在查詢辦公室聯絡資訊：{hit.group(1)}"
    return _STATIC_STATUS.get(node_name)


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


def _slow_text(seconds: int, live: bool) -> str:
    """The waiting notice for a threshold (rag/live/config.py SLOW_WARN_SECONDS); warn only, never abort."""
    what = "官網資料" if live else "資料"
    if seconds >= 300:
        return "已等待超過 5 分鐘，官網回應很慢。你可以先停止，改用資料庫的資料回答。" if live else "已等待超過 5 分鐘，系統回應很慢。你可以先停止後再試一次。"
    if seconds >= 120:
        return "已等待 2 分鐘以上，仍在等官網回應……" if live else "已等待 2 分鐘以上，仍在處理……"
    if seconds >= 60:
        return f"已等待 1 分鐘以上，仍在確認{what}，需要多一點時間……"
    return f"需要多一點時間，正在確認{what}……"


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
