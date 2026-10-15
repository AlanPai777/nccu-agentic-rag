"""
experiments/form_gate/run_gate_eval.py
P3.5 smoke test (docs/phase_j_live_fetch_plan.md): three cases, ONE gate call each. No requests to nccu.edu.tw (page
text comes from the git-tracked snapshot); the 3 LLM calls go to Ollama cloud like the rest of the pipeline.
This shows whether the prompt works on these 3 inputs once -- it is not evidence of stability.

    python experiments/form_gate/run_gate_eval.py          # dry-run: prints the 3 cases, sends nothing
    python experiments/form_gate/run_gate_eval.py --run    # 3 LLM calls
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).parent / "_out"
ACA_XIUXUE = "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學"
OSA_TUISU = "https://osa.nccu.edu.tw/tw/住宿輔導組/宿舍申請與床位資訊/退離宿程序"

CASES = [
    {"id": "A", "query": "退宿規定", "sub": "osa", "url": OSA_TUISU,
     "must": ["QP-M03-01-04", "QP-M03-01-05"], "optional": []},
    {"id": "B", "query": "如何辦理休學", "sub": "aca", "url": ACA_XIUXUE,
     "must": ["QP-T01-03-02"], "optional": ["QP-T01-02-05", "QP-T01-03-04"]},
    {"id": "C", "query": "如何辦理提早復學", "sub": "aca", "url": ACA_XIUXUE,
     "must": ["QP-T01-03-04"], "optional": ["QP-T01-02-05"]},
]


def snapshot_text(sub: str, url: str) -> str:
    target = unquote(url)
    with open(ROOT / "output" / sub / "extracted_texts.jsonl", encoding="utf-8") as fh:
        for line in fh:
            if target in unquote(line[:600]):
                d = json.loads(line)
                if unquote(d["url"]) == target:
                    return d["text"]
    raise SystemExit(f"snapshot page not found: {url}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    run = ap.parse_args().run

    from rag.agent_tools import extract_form_ids
    from rag.agentic.logic.form_gate import select_forms

    results = []
    for c in CASES:
        text = snapshot_text(c["sub"], c["url"])
        cands = sorted(extract_form_ids(text))
        print(f"[{c['id']}] {c['query']!r}  page={len(text)} chars  candidates={cands}")
        if not run:
            continue
        t0 = time.monotonic()
        g = select_forms(c["query"], text, cands)
        dt = time.monotonic() - t0
        kept_must = [f for f in c["must"] if f in g.fetch_ids]
        wrongly_skipped = [f for f in c["must"] if f in g.skipped]
        row = {"case": c["id"], "query": c["query"], "candidates": cands, "fetch": g.fetch_ids, "skipped": g.skipped,
               "fell_back": g.fell_back, "must": c["must"], "must_kept": kept_must, "must_wrongly_skipped": wrongly_skipped,
               "seconds": round(dt, 1), "raw": g.raw}
        results.append(row)
        print(f"    fetch={g.fetch_ids}  skipped={g.skipped}  fell_back={g.fell_back}  ({dt:.1f}s)")
        print(f"    must-fetch kept: {len(kept_must)}/{len(c['must'])}  {'OK' if len(kept_must) == len(c['must']) else 'MISSING ' + str(wrongly_skipped)}")
    if not run:
        print("\nDRY RUN: 3 LLM calls would be sent. Pass --run.")
        return
    OUT.mkdir(exist_ok=True)
    (OUT / "gate_smoke.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
