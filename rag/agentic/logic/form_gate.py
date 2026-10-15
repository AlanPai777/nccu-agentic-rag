"""
rag/agentic/logic/form_gate.py
P3.5 experiment (docs/phase_j_live_fetch_plan.md): decide, BEFORE fetching, which of the forms detected on a page
the question actually needs. One LLM call: question + the page's own text + the candidate forms' metadata ->
JSON saying fetch / skip per form.

Why this is not the pre-fetch judge Phase H removed (docs/phase_g_clean_pipeline_design.md N.1-N.4):
  * input is the page text only -- system-written header/marker lines are stripped first (the suspected cause of the
    "one extra newline flips the verdict" failure; suspected, never proven);
  * output is parsed JSON, not "which form ids appear anywhere in the reply";
  * only an EXPLICIT "fetch": false excludes a form. A missing id, malformed JSON, an exception or an empty reply
    all mean "fetch everything", i.e. the old fetch-all behaviour. The gate can only save work, never lose a form
    through its own failure to answer.
Off by default (FORM_GATE=on). Whether it is stable enough to keep is decided by experiments/form_gate/run_gate_eval.py.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

log = logging.getLogger("rag.form_gate")

_GATE_PROMPT = """你要判斷：回答下面這個問題，頁面裡提到的哪些表單需要抓取全文。

使用者問題：{query}

頁面內容：
{page}

頁面裡提到的表單（編號、標題、承辦單位、說明）：
{forms}

判斷方式：看頁面中提到每張表單的地方（它適用於哪種情況、什麼對象），對照使用者問題，判斷這張表單是不是辦理這件事會用到的。
- 辦理這件事會用到的表單：fetch 填 true。
- 明顯是另一種情境才用的表單（例如問題是申請成績單，而表單是申請獎學金專用）：fetch 填 false。
- 不確定時，fetch 填 true（漏抓比多抓嚴重）。

只回傳一個 JSON，不要有其他文字，每張表單一筆：
{{"forms": [{{"id": "表單編號", "fetch": true 或 false, "reason": "一句話理由"}}]}}"""

_SYSTEM_LINE_RE = re.compile(r"^(get_page 取得 |\[偵測到(表單編號|辦公室)|\[live:src )")
_BODY_MARK = "全文："


def clean_page_text(tool_text: str) -> str:
    """Page text only: drop the get_page header, detection markers and live-fetch ledger lines."""
    text = tool_text.split(_BODY_MARK, 1)[1] if _BODY_MARK in tool_text else tool_text
    return "\n".join(l for l in text.split("\n") if not _SYSTEM_LINE_RE.match(l.strip())).strip()


@lru_cache(maxsize=1)
def _metadata_by_id() -> dict[str, dict]:
    from rag.agentic.logic.form_extraction import _list_forms_metadata
    return {f["form_id"]: f for f in _list_forms_metadata(None)}


@dataclass
class GateResult:
    fetch_ids: list[str]
    skipped: dict[str, str] = field(default_factory=dict)    # id -> reason (explicit fetch:false only)
    fell_back: bool = False                                  # True: gate could not answer -> everything fetched
    raw: str = ""


def _parse(raw: str, candidates: list[str]) -> dict[str, tuple[bool, str]] | None:
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        data = json.loads(raw[start:end])
        rows = data["forms"]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(rows, list):
        return None
    out: dict[str, tuple[bool, str]] = {}
    for r in rows:
        if isinstance(r, dict) and r.get("id") in candidates and isinstance(r.get("fetch"), bool):
            out[r["id"]] = (r["fetch"], str(r.get("reason", "")))
    return out


def select_forms(query: str, page_text: str, candidates: list[str], llm=None) -> GateResult:
    """candidates: form ids already detected on the page (deterministically). llm: callable(prompt)->str; defaults
    to the project's simple_chat so the experiment uses the same model path as _judge_forms."""
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) <= 1:
        return GateResult(candidates)                        # nothing to choose between
    if llm is None:
        from rag.llm_client import simple_chat
        llm = lambda p: simple_chat(messages=[{"role": "user", "content": p}], max_tokens=600)
    meta = _metadata_by_id()
    forms = "\n".join(
        f"- {fid}：{meta.get(fid, {}).get('title', '（無 metadata）')}（{meta.get(fid, {}).get('unit', '')}）"
        for fid in candidates)
    prompt = _GATE_PROMPT.format(query=query, page=clean_page_text(page_text) or "（無內容）", forms=forms)
    try:
        raw = (llm(prompt) or "").strip()
    except Exception as e:                                   # noqa: BLE001 -- any failure means "fetch all"
        log.warning("form gate call failed (%s); fetching all", type(e).__name__)
        return GateResult(candidates, fell_back=True)
    verdict = _parse(raw, candidates)
    if verdict is None:
        log.warning("form gate reply unparseable; fetching all: %r", raw[:120])
        return GateResult(candidates, fell_back=True, raw=raw)
    skipped = {fid: why for fid, (fetch, why) in verdict.items() if fetch is False}
    fetch_ids = [fid for fid in candidates if fid not in skipped]       # omitted ids stay in
    if not fetch_ids:                                        # "none needed" from a gate we can't yet trust: fetch all
        log.warning("form gate excluded every form; fetching all")
        return GateResult(candidates, fell_back=True, raw=raw)
    return GateResult(fetch_ids, skipped, raw=raw)


def gate_enabled() -> bool:
    return os.environ.get("FORM_GATE", "off").strip().lower() == "on"
