"""
rag/live/ledger.py
Source ledger (docs/phase_j_live_fetch_plan.md §5.11). Every page the agent reads in `on` mode carries one
marker line in its ToolMessage header:

    [live:src status=live_same checked=2026-10-14T19:05 snap=2026-08-19 tls=0 url=https://aca.nccu.edu.tw/...]

The ledger is rebuilt from state["messages"] (no state field, so compaction and the add_messages reducer need
no changes). The user-visible 【資料狀態】 section is produced HERE, by program, from those markers -- the LLM
is not asked to word it, so it cannot forget or garble it.

Only the header of a ToolMessage is parsed (everything before "全文："), and live text is sanitized, so a
fetched page cannot forge a marker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote

from langchain_core.messages import HumanMessage, ToolMessage

DISCLOSURE_HEADER = "【資料狀態】"
BODY_SEPARATOR = "全文："
_MARKER_RE = re.compile(r"\[live:src ([^\]]*?) url=([^\]]+)\]")
_KV_RE = re.compile(r"(\w+)=(\S*)")

# states
LIVE_SAME, LIVE_CHANGED, LIVE_NEW = "live_same", "live_changed", "live_new"
SNAPSHOT_FALLBACK, LIVE_INCOMPLETE = "snapshot_fallback", "live_incomplete"
DISCONTINUED = "discontinued"      # moltke says the form is withdrawn; its content is not given to the LLM
FIXED_DATA = "fixed_data"          # contacts taken from KNOWN_CONTACTS (hard-coded in the source), not from any page
# Snapshot data was used without live confirmation -> the answer must say so.
NEEDS_DISCLOSURE = frozenset({SNAPSHOT_FALLBACK, LIVE_INCOMPLETE, FIXED_DATA})

_LABEL = {
    LIVE_SAME: "現場確認，內容與快照一致",
    LIVE_CHANGED: "現場確認，內容已更新（以現場為準）",
    LIVE_NEW: "現場取得（快照中沒有此頁）",
    SNAPSHOT_FALLBACK: "⚠ 現場確認失敗，使用快照（內容可能已過時）",
    LIVE_INCOMPLETE: "⚠ 現場頁面需瀏覽器渲染而無法完整取得，使用快照（內容可能已過時）",
    DISCONTINUED: "⚠ 官網顯示此表單已停用（未引用其內容）",
    FIXED_DATA: "⚠ 使用程式內建的固定聯絡資料（不是官網頁面，可能已過時）",
}
_ORDER = [DISCONTINUED, FIXED_DATA, SNAPSHOT_FALLBACK, LIVE_INCOMPLETE, LIVE_CHANGED, LIVE_NEW, LIVE_SAME]


@dataclass
class Source:
    url: str
    status: str
    checked: str
    snap: str
    tls_unverified: bool = False
    kind: str = "page"


def sanitize(text: str) -> str:
    """Keep fetched text from containing a literal marker prefix."""
    return text.replace("[live:src", "[live：src")


def make_marker(url: str, status: str, checked: str, snap: str, tls_unverified: bool = False, kind: str = "page") -> str:
    return f"[live:src status={status} kind={kind} checked={checked} snap={snap} tls={int(tls_unverified)} url={url}]"


# A form block inside resource_node's combined HumanMessage: the marker is trusted only when it sits on the line
# right after the "get_form 取得表單" header that get_form_tool writes.
_FORM_BLOCK_RE = re.compile(r"^get_form 取得表單[^\n]*\n(\[live:src [^\]]*?) url=([^\]\n]+)\]", re.M)
_MARKER_TOOL_PREFIXES = ("get_page 取得", "get_form 取得表單")
_FORM_MESSAGE_PREFIX = "[表單全文"
_CONTACT_MESSAGE_PREFIX = "[辦公室聯絡資訊"      # contact_node's block; its body is sanitized before the markers are appended
_UNCOVERED_RE = re.compile(r"\[contacts:snapshot-only offices=([^\]]*)\]")


def _source(attrs: str, url: str) -> Source | None:
    kv = dict(_KV_RE.findall(attrs))
    if "status" not in kv:
        return None
    return Source(url.strip(), kv["status"], kv.get("checked", ""), kv.get("snap", ""), kv.get("tls") == "1",
                  kv.get("kind", "page"))


def parse_markers(messages: list) -> list[Source]:
    """Latest marker per URL wins (a page read twice keeps its most recent status).
    Trusted places: the header of a ToolMessage (before "全文："), and get_form headers inside resource_node's
    "[表單全文" HumanMessage. Fetched text is sanitized on the way in, so it cannot add markers either."""
    out: dict[str, Source] = {}
    for m in messages:
        found: list[tuple[str, str]] = []
        content = str(m.content)
        if isinstance(m, ToolMessage):
            # only the output of the two tools that write markers: other tools (search/grep) echo corpus text with no
            # "全文：" separator, which must never be read as a header
            if content.startswith(_MARKER_TOOL_PREFIXES):
                found = [(mk.group(1), mk.group(2)) for mk in _MARKER_RE.finditer(content.split(BODY_SEPARATOR, 1)[0])]
        elif isinstance(m, HumanMessage) and content.startswith(_FORM_MESSAGE_PREFIX):
            found = [(mk.group(1), mk.group(2)) for mk in _FORM_BLOCK_RE.finditer(content)]
        elif isinstance(m, HumanMessage) and content.startswith(_CONTACT_MESSAGE_PREFIX):
            found = [(mk.group(1), mk.group(2)) for mk in _MARKER_RE.finditer(content)]
        for attrs, url in found:
            src = _source(attrs, url)
            if src:
                out[src.url] = src
    return list(out.values())


def needs_disclosure(sources: list[Source]) -> list[Source]:
    return [s for s in sources if s.status in NEEDS_DISCLOSURE]


def status_section(sources: list[Source], gate_none: list[str] | None = None,
                   uncovered: list[str] | None = None) -> str:
    """Empty string when nothing was read in `on` mode and the form gate made no "none needed" call (so `off`
    answers are byte-for-byte unchanged)."""
    if not sources and not gate_none and not uncovered:
        return ""
    lines = [f"\n\n---\n{DISCLOSURE_HEADER}（由系統依實際抓取結果產生）"]
    if gate_none:
        lines.append(f"- 本題未抓取表單：頁面列有 {'、'.join(gate_none)}，表單閘門判斷與本題無關")
    for st in _ORDER:
        group = [s for s in sources if s.status == st]
        if not group:
            continue
        unit = "個辦公室" if st == FIXED_DATA else "頁"
        lines.append(f"- {_LABEL[st]}：{len(group)} {unit}")
        for s in group:
            tls = "（此站憑證無法驗證）" if s.tls_unverified else ""
            shown = s.url.rsplit("/", 1)[-1] if s.url.startswith("fixed://") else unquote(s.url)
            lines.append(f"  - {shown}{tls}")
    snap = next((s.snap for s in sources if s.snap), "")
    checked = max((s.checked for s in sources if s.checked), default="")
    tail = []
    if checked:
        tail.append(f"檢查時間 {checked.replace('T', ' ')}（台北）")
    if snap and needs_disclosure(sources):
        tail.append(f"快照資料截至 {snap}")
    if tail:
        lines.append("- " + "；".join(tail))
    if uncovered:
        lines.append(f"- 以下辦公室的承辦人與分機未經現場確認，仍為快照資料：{'、'.join(uncovered)}")
    return "\n".join(lines)


_GATE_NONE_PREFIX = "[表單閘門判斷這題不需要抓取表單]"
_GATE_NONE_RE = re.compile(r"\[gate:none candidates=([^\]]*)\]")


def parse_gate_none(messages: list) -> list[str] | None:
    """Candidate form ids the gate declined to fetch, if resource_node recorded a "none needed" verdict
    (only trusted inside the HumanMessage that node itself wrote, identified by its fixed prefix)."""
    for m in messages:
        if isinstance(m, HumanMessage) and str(m.content).startswith(_GATE_NONE_PREFIX):
            mk = _GATE_NONE_RE.search(str(m.content))
            if mk:
                return [c for c in mk.group(1).split(",") if c]
    return None


def parse_uncovered(messages: list) -> list[str]:
    """Offices whose staff data did NOT get a live check (not in the index, or the live check itself failed), as
    recorded by contact_node in its own block."""
    out: list[str] = []
    for m in messages:
        if isinstance(m, HumanMessage) and str(m.content).startswith(_CONTACT_MESSAGE_PREFIX):
            mk = _UNCOVERED_RE.search(str(m.content))
            if mk:
                out += [o for o in mk.group(1).split("、") if o and o not in out]
    return out


def contact_markers_text(markers: list[str], uncovered: list[str]) -> str:
    text = "\n".join(markers)
    if uncovered:
        text += f"\n[contacts:snapshot-only offices={'、'.join(uncovered)}]"
    return text


def gate_none_message(candidates: list[str], offices: list[str]) -> str:
    text = f"{_GATE_NONE_PREFIX}\n[gate:none candidates={','.join(candidates)}]"
    return text + (f"\n\n[偵測到辦公室: {', '.join(offices)}]" if offices else "")


def split_footer(answer: str) -> tuple[str, str]:
    """(body, footer): lets the SSE server stream the footer after the token-streamed body."""
    i = answer.find("\n\n---\n" + DISCLOSURE_HEADER)
    return (answer, "") if i < 0 else (answer[:i], answer[i:])
