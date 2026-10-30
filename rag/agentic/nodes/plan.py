"""
rag/agentic/nodes/plan.py
plan_node: classification and compound-query detection, merged into one node because one node is simpler.

PROCEDURE and KNOWLEDGE are NOT different graph paths. The classification label is recorded for logging and self_eval
only, and both fall through to the same "knowledge" branch in _after_plan. CONTACT and RESOURCE get a genuine direct
route straight to contact_node or resource_node, skipping the main rewrite/domain_router/agent/tools loop entirely.
"""

from __future__ import annotations

import re

from langfuse import observe

from rag.router import route as _classify_query, _keyword_route
from rag.agentic.state import AgentState

# Split on 逗號/句號 (full-width and half-width) -- clause boundaries are
# the unit plan_node reasons about when checking for a compound query.
_CLAUSE_SPLIT_RE = re.compile(r'[，。,.]')


@observe(name="plan_node")
def plan_node(state: AgentState) -> dict:
    """Classification layer reusing rag/router.py's existing 2-layer
    keyword->LLM classifier -- not a new classifier, the exact one already
    validated in production.

    Checks for a compound query FIRST, before the single-label classifier
    runs at all -- reusing router.py's own _keyword_route() per clause
    (split on 逗號/句號), same "keyword first, zero LLM cost" layer
    production's query_decomposition_node already validated. A query is
    compound only if 2+ clauses resolve to DIFFERENT QueryTypes; a
    single-topic query with a mere pause is not (mirrors production's
    exact reasoning). This only catches CROSS-type compound queries
    ("休學，圖書館電話多少") -- same-TYPE compound queries ("休學和退學的
    差別") are a structural blind spot here, caught instead by
    self_eval_node's post-hoc full-query check."""
    clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(state["query"]) if c.strip()]
    if len(clauses) >= 2:
        types_found = {t for t in (_keyword_route(c) for c in clauses) if t is not None}
        if len(types_found) >= 2:
            return {"query_type": "compound"}
    result = _classify_query(state["query"], use_llm_fallback=True)
    return {"query_type": result.query_type.value}


def _after_plan(state: AgentState) -> str:
    qt = state.get("query_type")
    if qt == "compound":
        return "compound"
    if qt == "contact":
        return "contact"
    if qt == "resource":
        return "resource"
    return "knowledge"  # procedure + knowledge share one path
