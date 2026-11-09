"""
evaluation/run_system.py

評測階段 1（plan/phase_k_evaluation_design.md 第 4 節）：用 gold 裡的題目跑一次
agentic_rag，把答案與「讀進 context 的頁面原文」存成 prediction.json。

不改系統：agentic_rag.run() 回傳的 final_state["messages"] 已含所有工具輸出與
resource_node / contact_node 注入的內容（CLI 的 _render_messages 跳過了 HumanMessage，
但 state 裡有），這裡只是把它們存下來。

只跑 live=False（固定快照），不對 nccu.edu.tw 發任何請求。LIVE_BROWSER=off 與
LANGFUSE_TRACING_ENABLED=false 在 import 系統之前設好。

用法（在專案根目錄）：
  python evaluation/run_system.py evaluation/cashier_contact/gold.json
輸出：
  <gold 所在資料夾>/runs/<run_id>/prediction.json
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# 必須在 import agentic_rag 之前：Playwright 已安裝時，測試若走到 render 會啟動 Chromium
# 並請求真實網站（CLAUDE.md 的規定），Langfuse 沒開時 span 匯出會一直重試洗版。
os.environ["LIVE_BROWSER"] = "off"
os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_SOURCE_LINE_RE = re.compile(r"\n[ \t>#*\-]*[【\[]?(?:引用來源|參考來源|資料來源|來源)[】\]]?\s*[:：]")


def split_answer(answer: str) -> tuple[str, dict]:
    """答案 → 正文（評分用）。剝掉 synthesis_node 附加的【資料狀態】段，
    以及答案最後的「來源：」行。回傳 (正文, 被剝掉的部分)。"""
    from rag.live.ledger import DISCLOSURE_HEADER

    stripped = {"disclosure": "", "sources": ""}
    body = answer or ""
    i = body.find(DISCLOSURE_HEADER)
    if i != -1:
        stripped["disclosure"] = body[i:].strip()
        body = body[:i]
    body = re.sub(r"\s*-{3,}\s*$", "", body.rstrip())

    # 最後一個「來源：」之後，如果只剩網址或條列，才剝掉（避免誤砍正文中的「來源」二字）
    matches = list(_SOURCE_LINE_RE.finditer("\n" + body))
    if matches:
        m = matches[-1]
        tail = ("\n" + body)[m.start():]
        rest = _SOURCE_LINE_RE.sub("", tail, count=1)
        if all(re.match(r"^\s*([-*>]\s*)?(<?https?://\S+>?|\[.*?\]\(https?://\S+\))?\s*$", ln) for ln in rest.splitlines()):
            stripped["sources"] = tail.strip()
            body = ("\n" + body)[: m.start()].lstrip("\n")
    return body.strip(), stripped


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def serialize_context(messages) -> tuple[list[dict], list[dict]]:
    """messages → (context, tool_calls)。context 只收 ToolMessage 與 HumanMessage
    （工具輸出與 resource/contact 節點注入的內容）；AIMessage 的 tool_calls 另存成 trace。"""
    context, calls = [], []
    for i, m in enumerate(messages):
        kind = type(m).__name__
        if kind == "AIMessage":
            for c in getattr(m, "tool_calls", None) or []:
                calls.append({"message_index": i, "name": c.get("name"), "args": c.get("args")})
        elif kind in ("ToolMessage", "HumanMessage"):
            context.append({
                "message_index": i,
                "role": kind,
                "tool": getattr(m, "name", None),
                "text": _text(m.content),
            })
    return context, calls


_MARKER_RE = re.compile(r"\[live:src ([^\]]*?) url=([^\]]+)\]")   # same shape as rag/live/ledger.py
_KV_RE = re.compile(r"(\w+)=(\S*)")
_EXT_IN_LIST_RE = re.compile(r"分機\s*(\d{4,5})")
_INDEX_PATH = ROOT / "output" / "office_contacts_index.jsonl"


def _index_by_url() -> dict[str, dict]:
    by_url: dict[str, dict] = {}
    if _INDEX_PATH.exists():
        for line in _INDEX_PATH.open(encoding="utf-8"):
            rec = json.loads(line)
            if rec.get("url"):
                by_url.setdefault(rec["url"], rec)
    return by_url


def enrich_contact_context(context: list[dict]) -> tuple[list[dict], dict]:
    """聯絡人題的 context。contact_node 注入的是「整理過的清單」（LLM 實際看到的內容），不是頁面原文，
    所以 gold 的原文依據無法對它逐字比對。清單末尾的 ledger 標記（kind=contact）記錄了名單讀自哪些頁面
    （D24 修正後這個網址才可信），這裡用網址從 office_contacts_index.jsonl 查出頁面原文，另存成
    role=ContactPage 的 context 項目；清單本身標成 contact_list 保留（用來判斷「解析後保留了嗎」）。

    一致性檢查：清單列出的每個分機，都應出現在它所讀頁面的原文裡。不一致代表紀錄的網址不可信，
    或解析憑空產生了分機，評測結果要小心。"""
    index = _index_by_url()
    out, pages_added, checks = [], {}, {"contact_pages": [], "contact_consistency": []}
    context = [c for c in context if c.get("kind") != "contact_page"]     # 可重複執行：先拿掉上一次加的頁面
    for item in context:
        item = dict(item)
        text = item["text"]
        markers = [(dict(_KV_RE.findall(kv)), url) for kv, url in _MARKER_RE.findall(text)]
        contact_markers = [(kv, url) for kv, url in markers if kv.get("kind") == "contact"]
        if item["role"] != "HumanMessage" or "【各辦公室聯絡資訊】" not in text:
            out.append(item)
            continue
        item["kind"] = "contact_list"
        out.append(item)
        listed = set(_EXT_IN_LIST_RE.findall(text.split("[live:src")[0]))
        page_texts = []
        for kv, url in contact_markers:
            if url.startswith("fixed://"):
                checks["contact_pages"].append({"url": url, "source": "fixed_data", "found_in_index": False})
                continue
            rec = index.get(url)
            checks["contact_pages"].append({"url": url, "source": "index_snapshot", "found_in_index": bool(rec)})
            if not rec:
                continue
            page_texts.append(rec.get("text", ""))
            if url not in pages_added:
                pages_added[url] = True
                out.append({
                    "message_index": item["message_index"],
                    "role": "ContactPage",
                    "tool": "contact_node(page)",
                    "kind": "contact_page",
                    "source_url": url,
                    "snapshot_at": (rec.get("fetched_at") or "")[:10],
                    "text": rec.get("text", ""),
                })
        joined = re.sub(r"\s+", "", "".join(page_texts))
        missing = sorted(e for e in listed if e not in joined)
        # 清單裡的辦公室總機（來自 OFFICE_SOURCES 的舊頁面）不一定在人員頁裡，單獨列出、不算不一致
        checks["contact_consistency"].append({
            "listed_extensions": sorted(listed),
            "not_in_cited_pages": missing,
            "ok": (not missing) if page_texts else None,
        })
    return out, checks


def git_rev() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "rag", "agentic_rag.py", "server.py"],
                               cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        return out.stdout.strip() + ("+uncommitted" if dirty else "")
    except Exception:
        return "unknown"


def _print_checks(context: list[dict], checks: dict) -> None:
    pages = [c for c in context if c.get("kind") == "contact_page"]
    for p in pages:
        print(f"[contact 頁面] {p['source_url']}（快照 {p['snapshot_at']}，{len(p['text'])} 字）")
    for p in checks["contact_pages"]:
        if p["source"] == "fixed_data":
            print(f"[contact 內建固定資料] {p['url']}（不是頁面）")
        elif not p["found_in_index"]:
            # 紀錄的網址不在聯絡人索引裡 = 它不是名單讀自的人員頁（D24 修正前的紀錄就是這樣），查不到原文
            print(f"[警告] contact 紀錄的網址不在 office_contacts_index.jsonl：{p['url']}（查不到頁面原文，context 缺名單來源）",
                  file=sys.stderr)
    for c in checks["contact_consistency"]:
        if c["ok"] is False:
            print(f"[警告] 清單的分機不在所引頁面裡：{c['not_in_cited_pages']}（紀錄的網址可能不可信）", file=sys.stderr)
        elif c["ok"] is True:
            print(f"[一致性檢查] 清單 {len(c['listed_extensions'])} 個分機都在所引頁面裡")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gold", help="gold.json 路徑（題目取自其中的 query）")
    ap.add_argument("--query", default=None, help="改用這個問法（預設用 gold 的 query）")
    ap.add_argument("--reprocess", default=None, metavar="PREDICTION_JSON",
                    help="不重跑系統：把既有的 prediction.json 的 context 重新整理（不呼叫 LLM、不上網），結果另存 prediction.reprocessed.json")
    args = ap.parse_args()

    if args.reprocess:
        src = Path(args.reprocess).resolve()
        pred = json.loads(src.read_text(encoding="utf-8"))
        pred["context"], pred["checks"] = enrich_contact_context(pred["context"])
        out = src.with_name("prediction.reprocessed.json")
        out.write_text(json.dumps(pred, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _print_checks(pred["context"], pred["checks"])
        print(f"已寫入 {out.relative_to(ROOT)}")
        return

    gold_path = Path(args.gold).resolve()
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    query = args.query or gold["query"]

    live_env = os.environ.get("LIVE_FETCH")
    print(f"[run_system] LIVE_FETCH={live_env!r}, 這題用 live=False（不查現場）", file=sys.stderr)

    import agentic_rag  # noqa: E402  (env 必須先設好)
    from rag.llm_client import get_active_model

    started = dt.datetime.now().astimezone()
    final_state = agentic_rag.run(query, live=False)
    finished = dt.datetime.now().astimezone()

    answer_raw = final_state.get("answer") or ""
    body, stripped = split_answer(answer_raw)
    context, tool_calls = serialize_context(final_state.get("messages", []))
    context, checks = enrich_contact_context(context)

    run_id = started.strftime("%Y%m%d-%H%M%S")
    prediction = {
        "query_id": gold["query_id"],
        "query": query,
        "run_id": run_id,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "system_version": git_rev(),
        "model": get_active_model(),
        "live": False,
        "live_fetch_env": live_env,
        "answer_raw": answer_raw,
        "answer_body": body,
        "stripped": stripped,
        "context": context,
        "checks": checks,
        "trace": {
            "query_type": final_state.get("query_type"),
            "turn": final_state.get("turn"),
            "self_eval_note": final_state.get("self_eval_note"),
            "subdomain_hint": final_state.get("subdomain_hint"),
            "tool_calls": tool_calls,
        },
    }
    out_dir = gold_path.parent / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "prediction.json"
    out.write_text(json.dumps(prediction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"已寫入 {out.relative_to(ROOT)}")
    print(f"答案 {len(answer_raw)} 字（正文 {len(body)} 字）；context {len(context)} 筆、"
          f"{sum(len(c['text']) for c in context)} 字；工具呼叫 {len(tool_calls)} 次")
    _print_checks(context, checks)
    print("\n--- 答案正文 ---")
    print(body)


if __name__ == "__main__":
    main()
