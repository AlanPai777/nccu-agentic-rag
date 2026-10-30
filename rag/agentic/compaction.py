"""
rag/agentic/compaction.py
compact_previous_turn() -- collapses a closed conversation turn's raw
scratch work down to a clean [question, answer] pair before a new turn
starts on the same thread_id.

Why this exists: synthesis_node's _render_full_messages() renders the
*entire* messages list with no per-turn scoping, so an uncompacted
multi-turn conversation would leak a previous turn's fetched page/form/
office text into an unrelated new topic's synthesis prompt -- a correctness
risk, not just a growing-cost one. Trimming by message count (à la
CourseLangChain/agents/brain_agent.py's pre_model_hook) doesn't remove this
risk, only delays it, since stale cross-topic content can still be inside
whatever window survives.

Safe to reduce a turn down to just its answer because _SYNTHESIS_PROMPT
(rag/agentic/nodes/synthesis.py) rule 6 already requires the answer to end
with a 來源：URL citation -- verified to produce real 來源：lines in a regression run, not just a prompt promise. The compacted answer
is therefore already "conclusion + source" in one string.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage


def compact_previous_turn(graph, config: dict) -> None:
    """Call once, right before starting a new turn on an existing
    thread_id (config["configurable"]["thread_id"]) -- never mid-turn, since
    this assumes the previous turn already reached synthesis_node.

    No-ops on a brand-new thread_id (nothing to compact yet) and on a
    previous turn that never produced an answer (e.g. it errored before
    reaching synthesis_node) -- compacting to a [query, None] pair would
    just replace real scratch with a useless placeholder.

    Only removes THIS turn's own scratch (messages from state["compacted_boundary"]
    onward) and appends its [question, answer] pair after whatever prior turns'
    compacted pairs already sit before that boundary -- earlier turns' history is
    never touched. Before this boundary tracking existed, every call replaced ALL
    of `messages` with a single fresh [query, answer] pair built from state["query"]/
    state["answer"] (single-value fields, overwritten every turn) -- which silently
    discarded every earlier turn's already-compacted pair each time a new turn
    finished, so only the most recently finished turn ever survived (confirmed live:
    a 3rd turn's messages contained no trace of turn 1's content)."""
    snapshot = graph.get_state(config)
    values = snapshot.values or {}
    prev_messages = values.get("messages") or []
    prev_query = values.get("query")
    prev_answer = values.get("answer")
    if not prev_messages or not prev_query or not prev_answer:
        return

    boundary = values.get("compacted_boundary", 0)
    this_turn_scratch = prev_messages[boundary:]

    removals = [RemoveMessage(id=m.id) for m in this_turn_scratch if getattr(m, "id", None)]
    compacted = [HumanMessage(content=prev_query), AIMessage(content=prev_answer)]
    graph.update_state(config, {
        "messages": removals + compacted,
        "compacted_boundary": boundary + len(compacted),
    })
