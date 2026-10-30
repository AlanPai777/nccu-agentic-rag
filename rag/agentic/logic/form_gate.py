"""
rag/agentic/logic/form_gate.py
An experiment that is off by default. It decides, BEFORE fetching, which of the forms detected on a page the question
actually needs. One LLM call takes the question, the page's own text and the candidate forms' metadata, and returns
JSON saying fetch or skip for each form.

An earlier pre-fetch judge was removed because it excluded a form that was needed. This one differs in three ways:
  * The input is the page text only. System-written header and marker lines are stripped first. They are the
    suspected cause of the "one extra newline flips the verdict" failure, suspected but never proven.
  * The output is parsed JSON, not "which form ids appear anywhere in the reply".
  * Only an EXPLICIT "fetch": false excludes a form. A missing id, malformed JSON, an exception or an empty reply
    all mean "fetch everything", which is the old fetch-all behaviour, so failing to answer never loses a form.
    But a clear answer is honoured even when it is "none of them". The route may have been wrong from the start,
    so zero forms is a legitimate result and not a failure.
Off by default (FORM_GATE=on). Whether it is stable enough to keep is decided by running it against labelled cases.
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


def _record(query: str, candidates: list[str], r: GateResult) -> GateResult:
    """One log line per decision (LIVE_LOG=info prints it) so a wrong exclusion can be found afterwards -- the
    failure class that once cost an answer its refund table. The reasons live only in `r.skipped` otherwise."""
    log.info("form gate q=%r candidates=%s fetch=%s skipped=%s fell_back=%s", query, candidates, r.fetch_ids,
             r.skipped, r.fell_back)
    return r


def select_forms(query: str, page_text: str, candidates: list[str], llm=None) -> GateResult:
    """candidates: form ids already detected on the page (deterministically). llm: callable(prompt)->str. Defaults
    to the project's simple_chat so the experiment uses the same model path as _judge_forms."""
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) <= 1:
        return _record(query, candidates, GateResult(candidates))   # nothing to choose between
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
        return _record(query, candidates, GateResult(candidates, fell_back=True))
    verdict = _parse(raw, candidates)
    if verdict is None:
        log.warning("form gate reply unparseable; fetching all: %r", raw[:120])
        return _record(query, candidates, GateResult(candidates, fell_back=True, raw=raw))
    skipped = {fid: why for fid, (fetch, why) in verdict.items() if fetch is False}
    fetch_ids = [fid for fid in candidates if fid not in skipped]       # omitted ids stay in
    # fetch_ids may legitimately be EMPTY: every form explicitly marked fetch:false means the question needs none
    # (e.g. the route into resource_node was wrong to begin with). That verdict is honoured -- no fallback.
    return _record(query, candidates, GateResult(fetch_ids, skipped, raw=raw))


def gate_enabled() -> bool:
    return os.environ.get("FORM_GATE", "off").strip().lower() == "on"
