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
# Snapshot data was used without live confirmation -> the answer must say so.
NEEDS_DISCLOSURE = frozenset({SNAPSHOT_FALLBACK, LIVE_INCOMPLETE})

_LABEL = {
    LIVE_SAME: "現場確認，內容與快照一致",
    LIVE_CHANGED: "現場確認，內容已更新（以現場為準）",
    LIVE_NEW: "現場取得（快照中沒有此頁）",
    SNAPSHOT_FALLBACK: "⚠ 現場確認失敗，使用快照（內容可能已過時）",
    LIVE_INCOMPLETE: "⚠ 現場頁面需瀏覽器渲染而無法完整取得，使用快照（內容可能已過時）",
    DISCONTINUED: "⚠ 官網顯示此表單已停用（未引用其內容）",
}
# Kinds of data the agent may also cite that are NOT yet confirmed live (still the office index snapshot).
# Remove the entry when P4 (contacts) lands; P3 already removed 表單內容. Keeps the footer from over-claiming.
UNCHECKED_KINDS = ("承辦人與分機",)

_ORDER = [DISCONTINUED, SNAPSHOT_FALLBACK, LIVE_INCOMPLETE, LIVE_CHANGED, LIVE_NEW, LIVE_SAME]


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
_FORM_MESSAGE_PREFIX = "[表單全文"


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
            found = [(mk.group(1), mk.group(2)) for mk in _MARKER_RE.finditer(content.split(BODY_SEPARATOR, 1)[0])]
        elif isinstance(m, HumanMessage) and content.startswith(_FORM_MESSAGE_PREFIX):
            found = [(mk.group(1), mk.group(2)) for mk in _FORM_BLOCK_RE.finditer(content)]
        for attrs, url in found:
            src = _source(attrs, url)
            if src:
                out[src.url] = src
    return list(out.values())


def needs_disclosure(sources: list[Source]) -> list[Source]:
    return [s for s in sources if s.status in NEEDS_DISCLOSURE]


def status_section(sources: list[Source]) -> str:
    """Empty string when nothing was read in `on` mode (so `off` answers are byte-for-byte unchanged)."""
    if not sources:
        return ""
    lines = [f"\n\n---\n{DISCLOSURE_HEADER}（由系統依實際抓取結果產生）"]
    for st in _ORDER:
        group = [s for s in sources if s.status == st]
        if not group:
            continue
        lines.append(f"- {_LABEL[st]}：{len(group)} 頁")
        for s in group:
            tls = "（此站憑證無法驗證）" if s.tls_unverified else ""
            lines.append(f"  - {unquote(s.url)}{tls}")
    snap = next((s.snap for s in sources if s.snap), "")
    checked = max((s.checked for s in sources if s.checked), default="")
    tail = []
    if checked:
        tail.append(f"檢查時間 {checked.replace('T', ' ')}（台北）")
    if snap and needs_disclosure(sources):
        tail.append(f"快照資料截至 {snap}")
    if tail:
        lines.append("- " + "；".join(tail))
    if UNCHECKED_KINDS:
        lines.append(f"- 以上只涵蓋上列頁面；{'、'.join(UNCHECKED_KINDS)}尚未現場確認，仍為快照資料")
    return "\n".join(lines)


def split_footer(answer: str) -> tuple[str, str]:
    """(body, footer): lets the SSE server stream the footer after the token-streamed body."""
    i = answer.find("\n\n---\n" + DISCLOSURE_HEADER)
    return (answer, "") if i < 0 else (answer[:i], answer[i:])
