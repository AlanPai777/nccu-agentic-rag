"""
experiments/live_spikes/p4_step0_threads.py
P4 step 0 (docs/phase_j_live_fetch_plan.md): can Playwright's SYNC API be used the way the browser-owner-thread
design assumes? Local only -- pages are built with set_content(); nothing is sent to nccu.edu.tw, no LLM.

  T1  plain use in one thread (and how long does Chromium take to start?)
  T2  an object created in thread A used from thread B           (expected to fail: the reason for an owner thread)
  T3  owner-thread pattern: one thread owns the browser, other threads submit work through a queue
  T4  inside a LangGraph SYNC node run by astream (the server's path): (a) calling sync_playwright() directly in the
      node's thread; (b) calling the owner thread from the node, two separate graph invocations
  T5  sync_playwright() in a thread that HAS a running asyncio loop   (expected to fail; shows what the loop-free
      executor threads buy us)

    python experiments/live_spikes/p4_step0_threads.py
"""

from __future__ import annotations

import asyncio
import json
import queue
import sys
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import TypedDict

OUT = Path(__file__).parent / "_out"
HTML = "<html><body><div id='x'>hello 休學</div></body></html>"
results: dict[str, dict] = {}


def record(name: str, fn):
    t0 = time.monotonic()
    try:
        info = fn()
        results[name] = {"ok": True, "seconds": round(time.monotonic() - t0, 2), **(info or {})}
    except BaseException as e:      # noqa: BLE001 -- the failure IS the finding
        results[name] = {"ok": False, "seconds": round(time.monotonic() - t0, 2),
                         "error_type": type(e).__name__, "error": str(e).splitlines()[0][:160]}
    print(name, results[name], flush=True)


# ---- T1 ---------------------------------------------------------------------------------------------------------
def t1():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        t0 = time.monotonic()
        browser = pw.chromium.launch(headless=True)
        launch = time.monotonic() - t0
        page = browser.new_page()
        page.set_content(HTML)
        text = page.inner_text("#x")
        browser.close()
    return {"launch_seconds": round(launch, 2), "text": text}


# ---- T2 ---------------------------------------------------------------------------------------------------------
def t2():
    from playwright.sync_api import sync_playwright
    holder: dict = {}
    ready, done = threading.Event(), threading.Event()

    def thread_a():
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            holder["page"] = b.new_page()
            holder["page"].set_content(HTML)
            ready.set()
            done.wait(30)
            b.close()
    ta = threading.Thread(target=thread_a)
    ta.start()
    ready.wait(30)
    err: list[BaseException] = []

    def thread_b():
        try:
            holder["page"].inner_text("#x")          # object belongs to thread A
        except BaseException as e:                   # noqa: BLE001
            err.append(e)
    tb = threading.Thread(target=thread_b)
    tb.start()
    tb.join()
    done.set()
    ta.join()
    if not err:
        return {"cross_thread_use": "worked"}
    raise err[0]


# ---- T3 / owner thread (prototype of the real thing) -------------------------------------------------------------
class Owner:
    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            while True:
                item = self.q.get()
                if item is None:
                    break
                fut, html = item
                try:
                    page = browser.new_page()
                    page.set_content(html)
                    fut.set_result(page.inner_text("#x"))
                    page.close()
                except BaseException as e:           # noqa: BLE001
                    fut.set_exception(e)
            browser.close()

    def render(self, html: str) -> Future:
        fut: Future = Future()
        self.q.put((fut, html))
        return fut

    def close(self):
        self.q.put(None)
        self.thread.join(30)


def t3():
    owner = Owner()
    try:
        outs: list = []

        def caller(i):
            outs.append((i, threading.current_thread().name, owner.render(HTML.replace("hello", f"hello{i}")).result(30)))
        ts = [threading.Thread(target=caller, args=(i,), name=f"caller-{i}") for i in range(3)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    finally:
        owner.close()
    return {"results": sorted(outs)}


# ---- T4 ---------------------------------------------------------------------------------------------------------
class S(TypedDict):
    out: str
    thread: str


def _graph(node):
    from langgraph.graph import END, START, StateGraph
    g = StateGraph(S)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile()


def t4a():
    """sync node uses sync_playwright() directly -- in whatever thread LangGraph gives it."""
    def node(s):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            p = b.new_page()
            p.set_content(HTML)
            t = p.inner_text("#x")
            b.close()
        return {"out": t, "thread": threading.current_thread().name}

    async def run():
        outs = []
        async for chunk in _graph(node).astream({"out": "", "thread": ""}, stream_mode="updates"):
            outs.append(chunk["n"])
        return outs
    return {"updates": asyncio.run(run())}


def t4b():
    """sync node asks the owner thread; two separate invocations (maybe different executor threads)."""
    owner = Owner()

    def node(s):
        return {"out": owner.render(HTML).result(30), "thread": threading.current_thread().name}

    async def run():
        outs = []
        app = _graph(node)
        for _ in range(2):
            async for chunk in app.astream({"out": "", "thread": ""}, stream_mode="updates"):
                outs.append(chunk["n"])
        return outs
    try:
        return {"updates": asyncio.run(run())}
    finally:
        owner.close()


# ---- T5 ---------------------------------------------------------------------------------------------------------
def t5():
    async def run():
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:                # a loop is running in THIS thread
            pw.chromium.launch(headless=True).close()
    asyncio.run(run())


if __name__ == "__main__":
    for name, fn in [("T1_same_thread", t1), ("T2_cross_thread_use", t2), ("T3_owner_thread", t3),
                     ("T4a_langgraph_node_direct", t4a), ("T4b_langgraph_node_owner", t4b), ("T5_inside_running_loop", t5)]:
        record(name, fn)
    OUT.mkdir(exist_ok=True)
    (OUT / "p4_step0_threads.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(0)
