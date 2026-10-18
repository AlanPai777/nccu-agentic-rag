"""
Offline tests that pin the LangGraph facts the S5 event design rests on (docs/phase_j_live_fetch_plan.md, P8.3 S5.0). No LLM, no network.
If a LangGraph upgrade changes one of these, S5's event plumbing needs another look.   Run from the repo root:
    python -W ignore -m unittest experiments.live_spikes.test_live_s5_writer -v

The facts (measured with experiments/live_spikes/s5_stream_writer_spike.py, langgraph 1.2.11):
  * get_stream_writer() delivers from a sync node, from a @tool run by ToolNode, and from a tool called inside a node.
  * A plain thread-pool worker or threading.Thread CANNOT use the writer while a stream is being consumed ("Called get_config outside of a
    runnable context") -- but it can when it runs inside a copy of the node's context: ex.submit(contextvars.copy_context().run, fn, ...).
    (Under graph.invoke the writer is a no-op everywhere, so a worker bug would only show up when streaming.)
  * Two concurrent astream runs do not see each other's events.
"""

from __future__ import annotations

import asyncio
import contextvars
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, TypedDict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.config import get_stream_writer  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.graph.message import add_messages  # noqa: E402
from langgraph.prebuilt import InjectedState, ToolNode  # noqa: E402


class S(TypedDict):
    messages: Annotated[list, add_messages]
    who: str


@tool
def probe_tool(x: str, state: Annotated[dict, InjectedState]) -> str:
    """probe"""
    get_stream_writer()({"place": "tool_node", "who": state.get("who")})
    return "ok"


def graph_with(worker_mode: str):
    def node(state):
        get_stream_writer()({"place": "node", "who": state["who"]})
        return {}

    def agent(state):
        return {"messages": [AIMessage(content="", tool_calls=[{"name": "probe_tool", "args": {"x": "1"}, "id": "c1"}])]}

    def tool_in_node(state):
        @tool
        def inner(x: str) -> str:
            """inner"""
            get_stream_writer()({"place": "tool_in_node", "who": state["who"]})
            return "ok"
        inner.invoke({"x": "1"})
        return {}

    def workers(state):
        who = state["who"]
        w = get_stream_writer()
        with ThreadPoolExecutor(max_workers=3) as ex:
            if worker_mode == "ctx":
                futs = [ex.submit(contextvars.copy_context().run, lambda i=i: w({"place": "worker", "who": who, "i": i})) for i in range(3)]
                futs += [ex.submit(contextvars.copy_context().run, lambda: get_stream_writer()({"place": "worker_fresh", "who": who}))]
            else:
                futs = [ex.submit(lambda: w({"place": "worker", "who": who}))]
            for f in futs:
                f.result()
        ctx = contextvars.copy_context()
        t = threading.Thread(target=lambda: ctx.run(lambda: w({"place": "thread", "who": who})))
        t.start()
        t.join()
        return {}

    g = StateGraph(S)
    for name, fn in (("node", node), ("agent", agent), ("tool_in_node", tool_in_node), ("workers", workers)):
        g.add_node(name, fn)
    g.add_node("tools", ToolNode([probe_tool]))
    g.add_edge(START, "node"); g.add_edge("node", "agent"); g.add_edge("agent", "tools"); g.add_edge("tools", "tool_in_node")
    g.add_edge("tool_in_node", "workers"); g.add_edge("workers", END)
    return g.compile()


PLACES = ["node", "tool_node", "tool_in_node", "worker", "worker", "worker", "worker_fresh", "thread"]


async def collect(graph, who):
    out = []
    async for mode, payload in graph.astream({"messages": [], "who": who}, stream_mode=["updates", "custom"]):
        if mode == "custom":
            out.append(payload)
    return out


class TestWriter(unittest.TestCase):
    def test_every_place_delivers_under_astream_which_is_what_server_py_uses(self):
        events = asyncio.run(collect(graph_with("ctx"), "A"))
        self.assertEqual(sorted(e["place"] for e in events), sorted(PLACES))

    def test_every_place_delivers_under_sync_stream(self):
        events = list(graph_with("ctx").stream({"messages": [], "who": "A"}, stream_mode="custom"))
        self.assertEqual(sorted(e["place"] for e in events), sorted(PLACES))

    def test_invoke_with_nobody_listening_is_harmless(self):
        graph_with("ctx").invoke({"messages": [], "who": "A"})
        graph_with("plain").invoke({"messages": [], "who": "A"})          # a worker without the context copy is also fine here

    def test_events_come_in_the_order_of_the_work_even_across_threads_of_one_node(self):
        events = asyncio.run(collect(graph_with("ctx"), "A"))
        places = [e["place"] for e in events]
        self.assertEqual(places[:3], ["node", "tool_node", "tool_in_node"])
        self.assertEqual(places[-1], "thread")

    def test_concurrent_questions_do_not_see_each_others_events(self):
        async def both():
            return await asyncio.gather(collect(graph_with("ctx"), "A"), collect(graph_with("ctx"), "B"))
        a, b = asyncio.run(both())
        self.assertTrue(a and all(e["who"] == "A" for e in a))
        self.assertTrue(b and all(e["who"] == "B" for e in b))
        self.assertEqual((len(a), len(b)), (len(PLACES), len(PLACES)))

    def test_a_plain_worker_cannot_use_the_writer_while_streaming(self):
        """The reason events.py must hand workers a context copy. If this starts passing the plain way, the helper is no longer needed."""
        with self.assertRaises(Exception) as cm:
            asyncio.run(collect(graph_with("plain"), "A"))
        self.assertIn("runnable context", str(cm.exception.__cause__ or cm.exception) + repr(cm.exception))


if __name__ == "__main__":
    unittest.main()
