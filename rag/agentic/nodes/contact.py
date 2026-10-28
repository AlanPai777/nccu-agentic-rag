"""
rag/agentic/nodes/contact.py
contact_node -- deterministic office-contact lookup. It finds the offices mentioned in the text and looks each one up in
the office index, so it works for any office and not for a fixed list.
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage
from langfuse import observe

from rag.agentic.state import AgentState
from rag.agentic.logic.office_detection import _detect_offices
from rag.live import events
from rag.live.config import live_enabled

log = logging.getLogger("rag.live")


@observe(name="contact_node")
def contact_node(state: AgentState) -> dict:
    """Deterministically routed here by _after_tools, _after_resource, or
    _after_plan -- all three are objective gates: a marker on a
    ToolMessage/HumanMessage, or plan_node classifying the query CONTACT
    directly. One code path regardless of which gate routed here: read
    whatever context_text is available (last message's content, or the
    raw query itself if messages is still empty), run the existing
    deterministic _detect_offices() scan against it -- this works
    identically whether context_text is a fetched form's full text or the
    bare query "出納組電話幾號", since both are just text to scan. No
    separate "which mode am I in" branching needed.

    Wraps OfficeLookupSkill's batch lookup. Deliberately does NOT run
    offices through an LLM relevance filter the way resource_node's
    _judge_forms() filters form_ids -- offices detected from a form's own
    station list are a completeness requirement (ALL stations must
    appear, not a filterable relevance list), and a pre-fetch filter risks
    permanently losing a required station's contact info on a bad
    judgment call, with no fallback. Fetching all detected offices is
    cheap (single batch lookup); any filtering for what actually surfaces
    in the answer belongs in synthesis, after the data exists."""
    messages = state.get("messages") or []
    last = messages[-1] if messages else None
    # On the direct CONTACT route (plan_node -> contact_node, before any rewrite) the question is what is scanned, on EVERY turn. From
    # the second turn on `messages` is not empty (the previous turn's [question, answer] stays), so reading messages[-1] there scanned the
    # previous ANSWER. Every other entry (a marker after a tool, a form's text) still scans the last message.
    from_question = last is None or (state.get("query_type") == "contact" and state.get("turn", 0) == 0)
    context_text = state["query"] if from_question else str(last.content)
    offices = _detect_offices(context_text)
    if not offices:
        return {}
    from rag.agentic.logic.parent_offices import expand_parent_offices, triage
    offices, _parents, _skipped = triage(offices, from_question)
    if not offices:                                    # only parent units named in page text: nothing to look up
        log.info("contact: nothing to look up, skipped parent units %s", _skipped)
        return {}
    from rag.skills.office_lookup_skill import OfficeLookupSkill
    skill = OfficeLookupSkill()
    live = None
    use_live = live_enabled(state.get("live"))         # this question's choice, decided once
    with events.group("contacts", events.title_list(offices)) as grp:          # progress events for the front end
        live_ready, fetch_static, render = False, None, None
        if use_live:
            # Read the offices' staff pages live (Chromium), keep the snapshot where nothing changed. Any
            # failure here must leave the snapshot answer intact -- the live check is an addition, never a dependency.
            try:
                from rag.live.contacts import default_backends
                fetch_static, render = default_backends()
                live_ready = True
            except Exception as e:                           # noqa: BLE001
                log.warning("live contact check failed, using the snapshot: %s: %s", type(e).__name__, e)

        def read_batch(names):                         # one batch of a parent unit's children; None = use the snapshot
            if not live_ready:
                return None
            from rag.live.contacts import fetch_contact_pages
            return fetch_contact_pages(names, fetch_static, render)

        exp = expand_parent_offices(offices, from_question, skill, read_batch)
        live_plain = None
        if live_ready and exp.plain:
            try:
                from rag.live.contacts import fetch_contact_pages
                live_plain = fetch_contact_pages(exp.plain, fetch_static, render)   # emits one row per staff page as each settles
            except Exception as e:                           # noqa: BLE001
                log.warning("live contact check failed, using the snapshot: %s: %s", type(e).__name__, e)
        from rag.live.contacts import merge_contact_results
        live = merge_contact_results(exp.live, live_plain)
        plain_result = skill.run(exp.plain, live=live_plain) if exp.plain else {}
        result = {o: exp.entries.get(o) or plain_result[o] for o in exp.order}
        for parent, why in exp.fallback_notes.items():  # the children had nobody: the parent's own page (or KNOWN_CONTACTS) answers
            result[parent]["note"] = "；".join(x for x in (why, result[parent].get("note")) if x)
        offices = exp.order                            # what is shown and cited from here on: the children that had contacts, not the parent
        _emit_snapshot_rows(grp, offices, result, live_done=live is not None)
    header = (
        f"[辦公室聯絡資訊，以下是內容中提及的全部 {len(offices)} 個辦公室（{'、'.join(offices)}），"
        f"未經相關性篩選——這是完整清單，不代表每一個都跟這題直接相關。"
        f"是否每個都要寫進最終答案由你根據問題判斷，不要假設清單已經先篩過。]"
    )
    context = header + "\n\n" + skill.format_context(result)
    if use_live:
        context = _with_ledger(context, offices, result, live)
    elif state.get("live") is False:                   # live explicitly OFF for this question: record what was read, change nothing else
        context = _snapshot_ledger(context, offices, result)
    return {"messages": [HumanMessage(content=context)]}


def _snapshot_pages(offices: list[str], result: dict) -> tuple[dict[str, list[str]], dict[str, str]]:
    """({staff page url: the offices whose contacts were read from it}, {url: the index record's date}) for the contacts that came from a page
    (not from KNOWN_CONTACTS). Used by the snapshot ledger and by the progress rows."""
    from rag.live.contacts import plan_pages
    try:
        dates = {u: (info.get("snapshot_at") or "")[:10] for u, info in plan_pages(offices)[0].items()}
    except Exception:                                  # noqa: BLE001 -- the ledger is an addition, never a dependency
        dates = {}
    by_url: dict[str, list[str]] = {}
    for office, entry in result.items():
        url = entry.get("page_url")
        if entry.get("contacts_source") == "page" and url:
            by_url.setdefault(url, []).append(office)
    return by_url, dates


def _emit_snapshot_rows(grp, offices: list[str], result: dict, live_done: bool) -> None:
    """Progress rows for what was NOT checked live: the staff pages the contacts were read from when live was off (live_done=False. With a
    live check those pages already emitted their own rows) and the offices that fell back to KNOWN_CONTACTS (never a web page)."""
    from rag.live import config
    from rag.live.clock import taipei_minute
    if not live_done:
        by_url, dates = _snapshot_pages(offices, result)
        for url, offs in by_url.items():
            grp.row("done", url=url, title="、".join(offs) + " 人員頁", state="snapshot", kind="contact", snap=dates.get(url) or config.SNAPSHOT_ASOF)
    for office, entry in result.items():
        if entry.get("contacts_source") == "known_contacts":
            grp.row("done", url="", title=office, state="fixed_data", kind="contact", checked=taipei_minute())


def _snapshot_ledger(context: str, offices: list[str], result: dict) -> str:
    """The question turned live off: one "snapshot" marker per staff page the contact data was read from (the page each office's entry
    cites), titled with the offices it covers, and one "fixed_data" marker per office that fell back to KNOWN_CONTACTS. Nothing was checked, so
    there is no check time and no "uncovered" line."""
    from rag.live import config
    from rag.live.clock import taipei_minute
    from rag.live.ledger import FIXED_DATA, SNAPSHOT, contact_markers_text, make_marker, sanitize
    by_url, dates = _snapshot_pages(offices, result)
    markers = [make_marker(url, SNAPSHOT, "", dates.get(url) or config.SNAPSHOT_ASOF, kind="contact", title="、".join(offs) + " 人員頁")
               for url, offs in by_url.items()]
    now = taipei_minute()
    markers += [make_marker("fixed://KNOWN_CONTACTS/" + office, FIXED_DATA, now, "", False, kind="contact")
                for office, entry in result.items() if entry.get("contacts_source") == "known_contacts"]
    return sanitize(context) + "\n\n" + contact_markers_text(markers, []) if markers else context


def _with_ledger(context: str, offices: list[str], result: dict, live) -> str:
    """One marker per staff page that was (or should have been) checked live, one per office that fell back to the
    hard-coded KNOWN_CONTACTS, and the list of offices that got no live check at all -- so the answer's 【資料狀態】 can say
    exactly which people data is confirmed and which is not. The body is sanitized first: page-derived names/duties can
    never contain a marker of their own."""
    from rag.live import config
    from rag.live.clock import taipei_minute
    from rag.live.ledger import FIXED_DATA, contact_markers_text, make_marker, sanitize
    markers: list[str] = []
    if live is not None:
        markers += [make_marker(o.url, o.state, o.checked, (o.snapshot_at or config.SNAPSHOT_ASOF)[:10], o.tls_unverified,
                                kind="contact", title="、".join(o.offices) + " 人員頁")
                    for o in live.pages.values()]
    now = taipei_minute()
    markers += [make_marker("fixed://KNOWN_CONTACTS/" + office, FIXED_DATA, now, "", False, kind="contact")
                for office, entry in result.items() if entry.get("contacts_source") == "known_contacts"]
    uncovered = list(offices) if live is None else live.uncovered
    return sanitize(context) + "\n\n" + contact_markers_text(markers, uncovered)
