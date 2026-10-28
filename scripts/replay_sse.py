"""
scripts/replay_sse.py
A stand-in for server.py that replays a canned run, so the front end can be built and looked at WITHOUT the LLM and WITHOUT any request
to nccu.edu.tw. Same endpoints and event shapes as server.py (GET /config, GET /ask?question=&live=on|off), same port by default.

    python scripts/replay_sse.py                 # http://localhost:8001, real-time pacing
    python scripts/replay_sse.py --speed 5       # five times faster
    # /ask?question=...&live=on     a live run (pending rows, changes, one page that fell back to the database, a cached page)
    # /ask?question=...&live=off    the same question answered from the database (every row "使用資料庫")
    # add &scenario=slow            adds the 120 s / 300 s waiting notices (shown immediately), &scenario=error ends in an error payload

The events are produced by the REAL code (rag/live/events.py group/row, rag/live/sources.py build_sources), with only the clock and the pages made up,
so a field renamed there shows up here. THE DATA IS FICTIONAL: every answer starts with a notice saying so.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from langchain_core.messages import HumanMessage, ToolMessage  # noqa: E402

from rag.live import config as live_config, events, ledger  # noqa: E402
from rag.live.clock import taipei_minute  # noqa: E402
from rag.live.sources import build_sources  # noqa: E402

NOTICE = "【示意資料：這是重播的假資料，不是真實查詢結果】\n\n"
ANSWER = ("休學申請書（QP-T01-03-02）可在校務表單服務下載，填妥後送**註冊組**辦理；退費相關事項請洽**出納組**；"
          "國際學生另請聯絡**國際合作事務處**。\n\n聯絡人：註冊組 分機 63273、出納組 分機 62123、國合處 分機 63019。")
ACA = "https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學"
FORM = "https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail="

# (office, url, state, minutes ago it was checked, extras)
CONTACT_PAGES = [
    ("註冊組", "https://aca.nccu.edu.tw/zh/人員職掌-註冊", "live_changed", 0, {}),
    ("教務長室", "https://aca.nccu.edu.tw/zh/人員職掌-教務長室", "live_changed", 0, {}),
    ("住宿輔導組", "https://osa.nccu.edu.tw/tw/住宿輔導組/關於我們/成員介紹", "live_same", 0, {}),
    ("身心健康中心", "https://osa.nccu.edu.tw/tw/身心健康中心/業務職掌/成員介紹", "snapshot_fallback", 0, {}),
    ("出納組", "https://cashier.nccu.edu.tw/PageStaffing?fid=7994", "live_same", 0, {"tls": True}),
    ("國際合作事務處", "https://oic.nccu.edu.tw/Category/596", "live_changed", 0, {}),
    ("圖書館", "https://www.lib.nccu.edu.tw/p/404-1000-312.php?Lang=zh-tw", "live_same", 3, {"cached": True}),
]


def _ago(minutes: int) -> str:
    return taipei_minute(time.time() - minutes * 60)


def build_run(live: bool) -> tuple[list[tuple[float, dict]], list]:
    """([(seconds to wait before sending, SSE payload)], the messages the ledger markers live in). Rows come from the real events module: its
    `emit` is replaced by a collector for the duration of the build."""
    out: list[tuple[float, dict]] = []
    cur = {"wait": 0.0}

    def collect(event):
        out.append((cur["wait"], event))
        cur["wait"] = 0.0

    def gap(seconds):
        cur["wait"] += seconds

    msgs: list = []
    snap = live_config.SNAPSHOT_ASOF

    def marker(url, state, title, ago=0, kind="page", **kw):
        state = state if live else "snapshot"
        m = ledger.make_marker(url, state, "" if state == "snapshot" else _ago(ago), snap, title=title, kind=kind, **kw)
        msgs.append(ToolMessage(content="get_page 取得 100 字\n" + m + "\n\n全文：\n…", tool_call_id=str(len(msgs))))
        return m

    with mock.patch.object(events, "emit", collect):
        out.append((0.0, {"type": "meta", "live": live, "live_available": True, "snapshot_date": snap}))
        gap(0.4); collect({"type": "status", "text": "判斷問題類型：辦理流程"})
        gap(0.6); collect({"type": "status", "text": "搜尋詞：休學"})
        gap(0.5); collect({"type": "status", "text": "縮小搜尋範圍：教務處"})

        gap(0.4)
        with events.group("search", "休學") as g:
            gap(0.5); g.row("done", url=ACA, title="休學、保留學籍、退學、提早復學", state="snapshot")
        gap(0.5); collect({"type": "status", "text": "頁面提到：表單 QP-T01-03-02, QP-T01-03-04"})

        with events.group("page", "休學、保留學籍、退學、提早復學") as g:
            if live:
                rid = g.row("start", url=ACA, title="休學、保留學籍、退學、提早復學", state="pending")
                gap(1.6)
                g.row("done", rid=rid, url=ACA, title="休學、保留學籍、退學、提早復學", marker=marker(ACA, "live_same", "休學、保留學籍、退學、提早復學"), seconds=1.6)
            else:
                g.row("done", url=ACA, title="休學、保留學籍、退學、提早復學", marker=marker(ACA, "live_same", "休學、保留學籍、退學、提早復學"))

        gap(0.5)
        with events.group("form", "QP-T01-03-02, QP-T01-03-04", refine=True) as g:
            for fid, title, secs in (("QP-T01-03-02", "休學／保留學籍申請書", 2.4), ("QP-T01-03-04", "復學申請書", 2.1)):
                if live:
                    rid = g.row("start", url=FORM + fid, title=fid, state="pending", kind="form")
                    gap(secs)
                    g.row("done", rid=rid, url=FORM + fid, title=title, kind="form", seconds=secs, marker=marker(FORM + fid, "live_same", title, kind="form"))
                else:
                    g.row("done", url=FORM + fid, title=title, kind="form", marker=marker(FORM + fid, "live_same", title, kind="form"))
        gap(0.4); collect({"type": "status", "text": "表單提到辦公室：註冊組、出納組、國際合作事務處"})

        gap(0.3)
        with events.group("contacts", events.title_list([c[0] for c in CONTACT_PAGES])) as g:
            if live:
                rids = {c[0]: g.row("start", url=c[1], title=c[0] + " 人員頁", state="pending", kind="contact") for c in CONTACT_PAGES}
                for office, url, state, ago, extra in CONTACT_PAGES:                   # they finish one by one, osa slower (10 s apart)
                    secs = {"住宿輔導組": 4.0, "身心健康中心": 9.5}.get(office, 1.5)
                    gap(0.9 if office not in ("身心健康中心",) else 1.8)
                    m = marker(url, state, office + " 人員頁", ago, kind="contact", tls_unverified=extra.get("tls", False),
                               cached=extra.get("cached", False), age_min=ago if extra.get("cached") else None)
                    g.row("done", rid=rids[office], url=url, title=office + " 人員頁", marker=m, seconds=secs, kind="contact")
            else:
                for office, url, state, ago, extra in CONTACT_PAGES:
                    g.row("done", url=url, title=office + " 人員頁", kind="contact",
                          marker=marker(url, state, office + " 人員頁", kind="contact", tls_unverified=extra.get("tls", False)))
        gap(0.6); collect({"type": "status", "text": "資料已足夠，整理答案"})

    # the group "done" events measured nothing (the build ran in milliseconds): give them the waits the run would have had
    total_by_group: dict[str, float] = {}
    for _, e in out:
        if e.get("kind") == "row" and e.get("seconds"):
            total_by_group[e["group_id"]] = max(total_by_group.get(e["group_id"], 0.0), e["seconds"])
    for _, e in out:
        if e.get("kind") == "group" and e.get("phase") == "done":
            e["seconds"] = round(total_by_group.get(e["id"], 0.3), 1)
    return out, msgs


def sse(payload) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def replay(question: str, live: bool, scenario: str, speed: float):
    timeline, msgs = build_run(live)
    for wait, event in timeline:
        await asyncio.sleep(wait / speed)
        yield sse(event)
    if scenario == "slow":
        for secs, text in ((120, "已等待 2 分鐘，比平常久一些，仍在向官網確認資料，請再稍候。"),
                           (300, "已等待 5 分鐘，官網可能回應很慢或沒有回應。你可以按停止，之後再問一次，或關閉「查現場」改用資料庫的資料。")):
            yield sse({"type": "slow", "seconds": secs, "text": text})
            await asyncio.sleep(0.8 / speed)
    if scenario == "error":
        yield sse({"data": "抱歉，系統發生錯誤，暫時無法處理您的要求。（ReplayError）", "error": "scenario=error"})
        yield sse({"data": "SPECIAL_END_TOKEN"})
        return
    text = NOTICE + ANSWER
    for i in range(0, len(text), 3):
        await asyncio.sleep(0.03 / speed)
        yield sse({"data": text[i:i + 3]})
    await asyncio.sleep(0.2 / speed)
    yield sse(build_sources(msgs, live))
    yield sse({"data": "SPECIAL_END_TOKEN"})


def make_app(speed: float):
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse

    app = FastAPI()
    origins = [o.strip() for o in os.environ.get("ASSISTANT_FRONTEND_ORIGIN", "http://localhost:3001").split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])

    @app.get("/config")
    async def get_config():
        return {"live_available": True, "snapshot_date": live_config.SNAPSHOT_ASOF}

    @app.get("/ask")
    async def ask(question: str, session_id: str | None = None, subdomain: str | None = None, live: str | None = None, scenario: str = ""):
        return StreamingResponse(replay(question, (live or "off").strip().lower() == "on", scenario, speed), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--speed", type=float, default=1.0, help="2 = twice as fast")
    args = ap.parse_args()
    import uvicorn
    print(f"replaying a FICTIONAL run on http://localhost:{args.port} (speed x{args.speed:g}); no LLM, no request to nccu.edu.tw")
    uvicorn.run(make_app(args.speed), host="0.0.0.0", port=args.port)
