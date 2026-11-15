"""
rag/agentic/tools/search.py
search_texts: FTS5 + LLM-judge semantic search tool.
"""

from __future__ import annotations

from itertools import zip_longest
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from langfuse import observe

from rag.keyword_store import KeywordStore
from rag.agentic.logic.rewrite import _judge_candidates
from rag.live import events

FTS_DB = "rag/fts_proto3.db"
TOP_K = 5


def _search_one(ks: KeywordStore, q: str, subdomain: str | None) -> list[dict]:
    """One query, scoped to the subdomain hint with a global fallback when the scoped search is empty."""
    found = ks.search(q, top_k=TOP_K, subdomain=subdomain)
    return found or (ks.search(q, top_k=TOP_K, subdomain=None) if subdomain else [])


def _merge_candidates(first: list[dict], second: list[dict]) -> list[dict]:
    """Interleave two ranked lists (first's top hit first), dropping a url+chunk already taken. Each query keeps its own top hits."""
    out, seen = [], set()
    for pair in zip_longest(first, second):
        for c in pair:
            if c is None:
                continue
            key = (c["url"], c.get("chunk_index"))
            if key not in seen:
                seen.add(key)
                out.append(c)
    return out


@tool
@observe(as_type="tool", name="search_texts")
def search_texts(state: Annotated[dict, InjectedState]) -> str:
    """語意搜尋——用這一輪系統已經幫你重寫好的搜尋詞，內部會查FTS5全文索引並判斷候選是否相關。不需要自己給關鍵字，優先使用這個工具。"""
    rewritten = state["rewritten"]
    with events.group("search", rewritten) as g:       # progress event for the front end; the returned text is unchanged
        ks = KeywordStore(db_path=FTS_DB)
        hint = state.get("subdomain_hint")
        candidates = _search_one(ks, rewritten, hint)
        # The rewrite may drop the one word that tells similar pages apart (an organisation or programme name), so the question as asked is
        # searched too and the two result lists are merged: a general data-level safeguard, nothing specific to one question.
        original = (state.get("query") or "").strip()
        if original and original != rewritten:
            candidates = _merge_candidates(candidates, _search_one(ks, original, hint))
        if not candidates:
            return f"search_texts('{rewritten}') 無候選結果"
        judge = _judge_candidates(state["query"], candidates)
        if not judge.get("good_enough"):
            return f"search_texts('{rewritten}') 候選皆不相關，judge理由: {judge.get('reason','')}"
        idx = max(0, min((judge.get("selected_index") or 1) - 1, len(candidates) - 1))
        sel = candidates[idx]
        g.row("done", url=sel["url"], title=sel["title"], state="snapshot")      # the snapshot's pick: database data, not checked live
        return (f"search_texts('{rewritten}') 找到候選 [{sel['subdomain']}] {sel['title']}\n"
                f"URL: {sel['url']}\n(judge通過: {judge.get('reason','')})")
