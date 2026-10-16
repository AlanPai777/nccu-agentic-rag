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
        last = now
    total = time.monotonic() - t_run
    by_node: dict[str, float] = {}
    for node, dt, _ in rows:
        by_node[node] = by_node.get(node, 0.0) + dt
    print(f"\nTOTAL {total:.1f}s (graph run only)\nseconds attributed to the gap BEFORE each node's update, summed per node:")
    for node, dt in sorted(by_node.items(), key=lambda x: -x[1]):
        print(f"  {dt:6.1f}s  {node}")
    print("\n" + "=" * 70 + "\n" + str(state.get("answer")))
    print_score_report(state.get("answer"), QUERY_CRITERIA_MAP.get(query, EVAL_CRITERIA))


if __name__ == "__main__":
    main()
