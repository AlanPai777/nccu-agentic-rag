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


def git_rev() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "rag", "agentic_rag.py", "server.py"],
                               cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        return out.stdout.strip() + ("+uncommitted" if dirty else "")
    except Exception:
        return "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gold", help="gold.json 路徑（題目取自其中的 query）")
    ap.add_argument("--query", default=None, help="改用這個問法（預設用 gold 的 query）")
    args = ap.parse_args()

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
    print("\n--- 答案正文 ---")
    print(body)


if __name__ == "__main__":
    main()
