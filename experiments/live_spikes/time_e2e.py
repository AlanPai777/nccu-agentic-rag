"""
experiments/live_spikes/time_e2e.py
Run ONE question through the real graph and print WHERE THE TIME GOES: seconds since the start for every node update (the gap before
an update is that node's own time, LLM calls included) and for every rag.live / form-gate log line. Does not change any behaviour; the
production CLI (agentic_rag.py) is untouched. Honours LIVE_FETCH / FORM_GATE. Uses the real LLM and, with LIVE_FETCH=on, the real site.

    LIVE_FETCH=on python experiments/live_spikes/time_e2e.py "如何辦理休學"
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


import collections
import functools

TIMERS: dict[str, list[float]] = collections.defaultdict(list)


def timed(label, fn):
    """Wrap fn so each call's duration lands in TIMERS[label]. Only used on module attributes, from here: no production edit."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        t = time.monotonic()
        try:
            return fn(*a, **k)
        finally:
            TIMERS[label].append(time.monotonic() - t)
    return wrapper


def install_probes() -> None:
    import rag.agentic.logic.office_detection as od
    import rag.agentic.nodes.contact as contact
    import rag.agentic.nodes.resource as resource
    import rag.agentic.tools.form as form
    import rag.agentic.tools.page as page
    import rag.live.contacts as lc
    import rag.skills.office_lookup_skill as sk
    od.simple_chat = timed("LLM  _detect_offices judge", od.simple_chat)
    sk.simple_chat = timed("LLM  contact page re-read (_llm_extract_contacts)", sk.simple_chat)
    page._get_page_raw = timed("get_page_tool: local snapshot lookup", page._get_page_raw)
    page.apply_page = timed("get_page_tool: live check", page.apply_page)
    form._get_form_raw = timed("get_form_tool: local snapshot lookup (per form)", form._get_form_raw)
    form.apply_form = timed("get_form_tool: live fetch (per form)", form.apply_form)
    for name in ("_extract_station_roles", "_extract_checklist_blocks", "_offices_from_role_keywords"):
        setattr(resource, name, timed(f"resource_node: {name}", getattr(resource, name)))
    resource._detect_offices = timed("resource_node: _detect_offices (incl. its LLM)", resource._detect_offices)
    contact._detect_offices = timed("contact_node: _detect_offices (incl. its LLM)", contact._detect_offices)
    lc.fetch_contact_pages = timed("contact_node: fetch_contact_pages (live pages)", lc.fetch_contact_pages)
    sk.OfficeLookupSkill.run = timed("contact_node: OfficeLookupSkill.run (incl. the live pages)", sk.OfficeLookupSkill.run)


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "如何辦理休學"
    t0 = time.monotonic()

    class Elapsed(logging.Formatter):
        def format(self, record):
            return f"{time.monotonic() - t0:7.1f}s  [log] {unquote(record.getMessage())[:150]}"
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(Elapsed())
    for name in ("rag.live", "rag.form_gate"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        lg.addHandler(h)

    from agentic_rag import build_graph, initial_state
    from rag.eval import EVAL_CRITERIA, QUERY_CRITERIA_MAP, print_score_report
    from rag.live.config import live_mode

    install_probes()
    graph = build_graph()
    print(f"LIVE_FETCH={live_mode()}  query={query!r}  (graph ready after {time.monotonic() - t0:.1f}s of imports/compile)")
    t_run = time.monotonic()
    last = t_run
    state = dict(initial_state(query))
    rows = []
    for update in graph.stream(initial_state(query), stream_mode="updates"):
        now = time.monotonic()
        for node, delta in update.items():
            delta = delta or {}
            rows.append((node, now - last, now - t_run))
            print(f"{now - t_run:7.1f}s  +{now - last:5.1f}s  node {node:20s} {list(delta.keys())}")
            for k, v in delta.items():
                state[k] = (state.get("messages", []) + v) if k == "messages" else v
            if node == "self_eval_node":
                print(f"           self_eval_note: {str(delta.get('self_eval_note'))[:300]!r}")
                for m in delta.get("messages", []):
                    print(f"           self_eval message: {str(m.content)[:400]!r}")
        last = now
    total = time.monotonic() - t_run
    by_node: dict[str, float] = {}
    for node, dt, _ in rows:
        by_node[node] = by_node.get(node, 0.0) + dt
    print(f"\nTOTAL {total:.1f}s (graph run only)\nseconds attributed to the gap BEFORE each node's update, summed per node:")
    for node, dt in sorted(by_node.items(), key=lambda x: -x[1]):
        print(f"  {dt:6.1f}s  {node}")
    print("\ninside the nodes (each call timed separately; a wrapper's time includes the wrapped calls):")
    for label, v in sorted(TIMERS.items(), key=lambda x: -sum(x[1])):
        print(f"  {sum(v):6.1f}s  x{len(v):<2d} {label}   {[round(x, 1) for x in v]}")
    print("\n" + "=" * 70 + "\n" + str(state.get("answer")))
    print_score_report(state.get("answer"), QUERY_CRITERIA_MAP.get(query, EVAL_CRITERIA))


if __name__ == "__main__":
    main()
