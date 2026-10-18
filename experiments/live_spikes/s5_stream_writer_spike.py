"""
experiments/live_spikes/s5_stream_writer_spike.py
P8 S5.0: can LangGraph's get_stream_writer() send custom events from every place the live code needs to? No LLM, no network: a fake graph.

Places tried (each emits one event):
  node            a plain sync node
  tool_node       a @tool run by ToolNode (like get_page_tool in the agent loop)
  tool_in_node    a @tool called as tool.invoke(...) from inside a node (like resource_node -> get_form_tool before S1)
  worker_plain    a ThreadPoolExecutor worker handed the writer captured in the node thread (found NOT to work: the writer needs LangGraph's
                  run context, which a plain worker thread does not have)
  worker_direct   a worker that calls get_stream_writer() itself (does not work either)
  worker_ctx      a worker submitted as ex.submit(contextvars.copy_context().run, fn): it runs inside a copy of the node's context
  bare_ctx        a plain threading.Thread started with the same context copy (like the prefetch background chain would be)

Consumers tried: graph.astream(stream_mode=["updates","custom"]) (server.py), graph.stream, and graph.invoke (CLI: nobody listens).

    python experiments/live_spikes/s5_stream_writer_spike.py
"""

from __future__ import annotations

import asyncio
import contextvars
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, TypedDict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.config import get_stream_writer  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.graph.message import add_messages  # noqa: E402
from langgraph.prebuilt import InjectedState, ToolNode  # noqa: E402

LOG: list[str] = []          # what each place reported about itself (errors etc.), printed at the end


class S(TypedDict):
    messages: Annotated[list, add_messages]
    live: bool | None


def emit(w, place, **kw):
    w({"type": "step", "place": place, "thread": threading.current_thread().name, **kw})


@tool
def probe_tool(x: str, state: Annotated[dict, InjectedState]) -> str:
    """probe"""
    emit(get_stream_writer(), "tool_node", live=state.get("live"))
    return "ok"


def node(state):
    emit(get_stream_writer(), "node")
    return {}


def agent(state):
    return {"messages": [AIMessage(content="", tool_calls=[{"name": "probe_tool", "args": {"x": "1"}, "id": "c1"}])]}


def tool_in_node(state):
    # resource_node style: the node calls a tool's function itself
    @tool
    def inner(x: str) -> str:
        """inner"""
        emit(get_stream_writer(), "tool_in_node")
        return "ok"
    inner.invoke({"x": "1"})
    return {}


def attempt(label, fn):
    """Run fn, record in LOG whether it worked; never let a failure abort the graph."""
    try:
        fn()
        return "ok"
    except Exception as e:                                       # noqa: BLE001
        LOG.append(f"{label}: {type(e).__name__}: {e}"[:150])
        return "failed"


def workers(state):
    w = get_stream_writer()                                   # captured in the node's own thread
    results = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        results["worker_plain"] = {attempt("worker_plain", lambda: ex.submit(emit, w, "worker_plain").result())}
        results["worker_direct"] = {attempt("worker_direct", lambda: ex.submit(lambda: emit(get_stream_writer(), "worker_direct")).result())}
        # a fresh copy of the node's context for EVERY task (one Context cannot be entered by two threads at once)
        futs = [ex.submit(contextvars.copy_context().run, emit, w, "worker_ctx", i=i) for i in range(4)]
        results["worker_ctx"] = {attempt("worker_ctx", f.result) for f in futs}
        futs = [ex.submit(contextvars.copy_context().run, lambda i=i: emit(get_stream_writer(), "worker_ctx_fresh", i=i)) for i in range(2)]
        results["worker_ctx_fresh"] = {attempt("worker_ctx_fresh", f.result) for f in futs}
    LOG.append("results: " + ", ".join(f"{k}={sorted(v)}" for k, v in results.items()))
    return {}


def bare_thread(state):
    w = get_stream_writer()
    out = []
    t = threading.Thread(target=lambda: out.append(attempt("bare_plain", lambda: emit(w, "bare_plain"))), name="bare-plain")
    t.start(); t.join()
    ctx = contextvars.copy_context()
    t = threading.Thread(target=lambda: out.append(attempt("bare_ctx", lambda: ctx.run(emit, w, "bare_ctx"))), name="bare-ctx")
    t.start(); t.join()
    LOG.append(f"bare threads: plain={out[0]}, ctx={out[1]}")
    return {}


def build():
    g = StateGraph(S)
    g.add_node("node", node)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode([probe_tool]))
    g.add_node("tool_in_node", tool_in_node)
    g.add_node("workers", workers)
    g.add_node("bare_thread", bare_thread)
    g.add_edge(START, "node")
    g.add_edge("node", "agent")
    g.add_edge("agent", "tools")
    g.add_edge("tools", "tool_in_node")
    g.add_edge("tool_in_node", "workers")
    g.add_edge("workers", "bare_thread")
    g.add_edge("bare_thread", END)
    return g.compile()


def summarize(label, events):
    places = [e["place"] for e in events]
    print(f"\n{label}: {len(events)} custom events")
    for e in events:
        print(f"   {e['place']:16s} thread={e['thread']}")
    return places


async def run_async(graph):
    ev, order = [], []
    async for mode, payload in graph.astream({"messages": [], "live": True}, stream_mode=["updates", "custom"]):
        if mode == "custom":
            ev.append(payload)
            order.append(("custom", payload["place"]))
        else:
            order.append(("updates", list(payload.keys())[0]))
    return ev, order


def main():
    graph = build()

    ev, order = asyncio.run(run_async(graph))
    places = summarize("astream(['updates','custom'])  [what server.py uses]", ev)
    print("   interleaving with node updates:", " > ".join(f"{k}:{v}" for k, v in order))

    ev2 = []
    for payload in graph.stream({"messages": [], "live": True}, stream_mode="custom"):
        ev2.append(payload)
    summarize("stream(stream_mode='custom')", ev2)

    print("\ninvoke() with nobody listening (the CLI):")
    try:
        graph.invoke({"messages": [], "live": True})
        print("   finished without error")
    except Exception as e:                                     # noqa: BLE001
        print(f"   RAISED {type(e).__name__}: {e}")

    print("\nnotes:")
    for line in LOG:
        print("  ", line)
    print("\nplaces that delivered at least one event:", sorted(set(places)))


if __name__ == "__main__":
    main()
