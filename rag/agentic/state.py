"""
rag/agentic/state.py
Shared LangGraph state for agentic_rag.py's pipeline.

Every node is built around state["messages"], a list of LangChain AIMessage, ToolMessage and HumanMessage objects.
ToolNode, InjectedState and the deterministic marker routing (_FORM_MARKER_RE and _OFFICE_MARKER_RE checking the last
ToolMessage's content) all depend on that shape. So the state is deliberately small and holds no separate structured
fields such as a list of sub-queries or an extraction checklist. Nothing would read them. Compound-query handling does
not need a stored sub-query list either, because multi_sub_query_node splits state["query"] again each time.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    query:          str
    subdomain_hint: str | None  # set once by domain_router_node (turn 1), reused
                                 # for the rest of the loop
    query_type:     str | None  # "procedure" / "contact" / "resource" / "knowledge" /
                                 # "compound" -- set by plan_node. PROCEDURE is
                                 # a label only, not a distinct graph path
    turn:           int         # incremented once per rewrite_node/agent_node cycle;
                                 # doom-loop/risk-ceiling checks read this
    rewritten:      str         # this turn's rewrite_node output
    stuck_turns:    int         # consecutive-identical-tool-call counter (doom-loop
                                 # detection, _MAX_STUCK)
    messages:       Annotated[list, add_messages]  # AIMessage/ToolMessage/HumanMessage
                                                     # history. add_messages is the
                                                     # reducer LangChain's ToolNode and
                                                     # ChatOllama.bind_tools() expect
    answer:         str | None  # final answer, written by synthesis_node
    self_eval_note: str | None  # the output of self_eval's Stage 1 or Stage 2
    today:          str         # YYYY-MM-DD in
                                 # Asia/Taipei, refilled every turn by initial_state() via
                                 # rag/live/clock.py. It is the reference date that "今天", "10/14" and "本週"
                                 # resolve against. No node reads it yet.
    live:           bool | None  # this question's "查現場" choice (front end switch via /ask?live=, CLI --live);
                                 # None = not said, rag/live/config.py live_enabled() then falls back to LIVE_FETCH alone.
                                 # Refilled every turn by initial_state().
    compacted_boundary: int     # server.py-only (multi-turn compaction): index into
                                 # `messages` where the in-progress turn's own live scratch
                                 # begins -- everything before it is already-compacted
                                 # prior-turn [question, answer] history that
                                 # compact_previous_turn() (rag/agentic/compaction.py) must
                                 # never touch again. Deliberately absent from
                                 # agentic_rag.py's initial_state() so each new turn's state
                                 # update leaves whatever compact_previous_turn() last wrote
                                 # here untouched (LangGraph only overwrites keys present in
                                 # an update payload) -- only compact_previous_turn() itself
                                 # ever sets it. Assumes nothing else in the graph ever calls
                                 # RemoveMessage on `messages` -- if that ever changes, this
                                 # index needs to move with it.
