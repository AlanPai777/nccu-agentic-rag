#!/usr/bin/env python3
"""
evaluation/batch.py

真實批次：一次依序跑 11 題（階段 A），離線計分並出總表，之後匯出儀表板的 .jsonl 與跨題報告。
設計與所有決定：plan/phase_k_evaluation_design.md 13.18。子代理回推與 Keypoint 判斷（階段 B）**不在這裡**，
由 run-eval-question skill 的批次模式一題一題做。

子命令（在專案根目錄）：
  python evaluation/batch.py plan   [--only 1,2]                       預檢並印出這批會做什麼（離線，不送任何請求）
  python evaluation/batch.py run    [--run] [--resume batchNN] ...      跑階段 A；沒有 --run 只是預演（同 plan）
  python evaluation/batch.py status batchNN                             每題做到哪一步（只看檔案，離線）
  python evaluation/batch.py export batchNN                             dashboard.jsonl 與 report.md（離線）

安全規則（寫死在程式裡，不靠記得）：
  * run 沒有 --run 一律是預演。--run 會呼叫 ollama，而且預設 live 開、會對 nccu.edu.tw 送請求，
    所以只有使用者這一輪明說「跑」才能加 --run。
  * 每題一個子程序，各自有逾時上限（預設 600 秒，到了連同 Chromium 子程序一起殺掉）。逾時、出錯都記成那題的結果，
    不自動重跑；碰到 402（ollama 額度用完）立刻整批停下，已存的題目保留，--resume 接著跑。
  * 這支程式不呼叫 Claude、不開子代理。
輸出：evaluation/batches/batchNN/{manifest.json, summary.md, logs/Qxx.log, dashboard.jsonl, report.md}；
  各題的 runs/runNN/ 在題目資料夾裡（和單題跑法相同）。
"""
import argparse
import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

EVAL = Path(__file__).resolve().parent
ROOT = EVAL.parent
BATCHES = EVAL / "batches"
QUESTIONS_FILE = EVAL / "batch_questions.json"
DEFAULT_TIMEOUT = 600
_BATCH_RE = re.compile(r"^batch(\d+)$")
_QUOTA_RE = re.compile(r"\b402\b|Payment Required", re.I)
_MARKER_RE = re.compile(r"\[live:src ([^\]]*?) url=([^\]]+)\]")
_KV_RE = re.compile(r"(\w+)=(\S*)")

if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))


# ---------- 小工具 ----------
def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(p: Path, obj) -> None:
    """先寫暫存檔再換名，程式中途被殺也不會留下寫一半的 manifest。"""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, p)


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def load_questions(only: set[int] | None = None, root: Path = EVAL) -> list[dict]:
    qs = _read(root / "batch_questions.json")["questions"]
    if only:
        unknown = only - {q["id"] for q in qs}
        if unknown:
            raise SystemExit(f"沒有這些題號：{sorted(unknown)}")
        qs = [q for q in qs if q["id"] in only]
    return qs


def new_batch_id(batches_dir: Path) -> str:
    nums = [int(m.group(1)) for p in batches_dir.glob("batch*") if p.is_dir() and (m := _BATCH_RE.match(p.name))] if batches_dir.exists() else []
    return f"batch{max(nums, default=0) + 1:02d}"


def git_state() -> dict:
    """系統版本與評測資料夾是否有未提交的修改（有就寫進 manifest 並警告）。"""
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        dirty_sys = subprocess.run(["git", "status", "--porcelain", "--", "rag", "agentic_rag.py", "server.py"],
                                   cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        dirty_eval = subprocess.run(["git", "status", "--porcelain", "--", "evaluation"],
                                    cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        return {"commit": rev, "system_uncommitted": bool(dirty_sys), "evaluation_uncommitted": bool(dirty_eval)}
    except Exception:
        return {"commit": "unknown", "system_uncommitted": None, "evaluation_uncommitted": None}


# ---------- 預檢（離線） ----------
def preflight(questions: list[dict], live: bool, root: Path = EVAL, env: dict | None = None) -> tuple[list[str], list[str]]:
    """回傳 (errors, warnings)。errors 非空就不該開跑。完全離線：不呼叫 LLM、不上網，也不探測 ollama。"""
    env = os.environ if env is None else env
    errors, warnings = [], []
    import gold_check
    for q in questions:
        gp = root / q["question"] / "gold.json"
        if not gp.exists():
            errors.append(f"Q{q['id']} {q['question']}：找不到 gold.json")
            continue
        problems = gold_check.validate_gold(gp)
        if problems:
            errors.append(f"Q{q['id']} {q['question']}：gold 檢查不過（{problems[0]}…共 {len(problems)} 項）")
    if live:
        raw = env.get("LIVE_FETCH", "").strip().lower()
        if raw not in ("", "on"):
            errors.append(f"LIVE_FETCH={env.get('LIVE_FETCH')!r} 是總開關（off 或無法辨識），系統不會查現場；清空或設成 on")
    g = git_state()
    if g["system_uncommitted"]:
        warnings.append("系統程式（rag/、agentic_rag.py、server.py）有未提交的修改：這批結果的版本會標 +uncommitted")
    if g["evaluation_uncommitted"]:
        warnings.append("evaluation/ 有未提交的修改（gold、登記表或評測程式）")
    return errors, warnings


# ---------- 子程序（含逾時） ----------
def run_child(cmd: list[str], timeout: int, log_path: Path, env: dict | None = None, cwd: Path = ROOT) -> dict:
    """跑一個子程序，輸出寫進 log_path。到了 timeout 就連整個行程群組（含 Chromium）一起殺。
    回傳 {"returncode", "timed_out", "elapsed", "tail"}。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now()
    timed_out = False
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=cwd, env=env, start_new_session=True)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
    tail = log_path.read_bytes()[-3000:].decode("utf-8", "replace")
    return {"returncode": proc.returncode, "timed_out": timed_out,
            "elapsed": round((dt.datetime.now() - started).total_seconds(), 1), "tail": tail}


def classify(res: dict, run_dir: Path) -> str:
    """ok｜timeout｜quota（ollama 額度用完，整批要停）｜error。"""
    if res["timed_out"]:
        return "timeout"
    if res["returncode"] == 0 and (run_dir / "prediction.json").exists():
        return "ok"
    if _QUOTA_RE.search(res["tail"]):
        return "quota"
    return "error"


def write_failure_stub(run_dir: Path, q: dict, status: str, res: dict, label: str, version: str, live: bool, browser: bool, timeout: int):
    """逾時或出錯的題目也留一個 run：沒有答案，儀表板上看得到那題失敗了。"""
    run_dir.mkdir(parents=True, exist_ok=False)
    _write(run_dir / "prediction.json", {
        "status": status, "elapsed_seconds": res["elapsed"], "query_id": q["question"], "run_id": run_dir.name, "label": label,
        "finished_at": _now(), "system_version": version, "live": live, "browser": browser,
        "answer_raw": "", "answer_body": "", "stripped": {}, "context": [], "checks": {}, "trace": {},
        "failure": {"timeout_seconds": timeout if status == "timeout" else None, "returncode": res["returncode"],
                    "log_tail": res["tail"][-1500:]},
    })


# ---------- 階段 A ----------
def run_batch(batch_dir: Path, questions: list[dict], live: bool, browser: bool, timeout: int,
              runner=run_child, root: Path = EVAL, label: str = "", say=print, retry_failed: bool = False) -> dict:
    import run_system
    manifest_path = batch_dir / "manifest.json"
    manifest = _read(manifest_path) or {
        "batch_id": batch_dir.name, "created_at": _now(), "git": git_state(), "live": live, "browser": browser,
        "timeout_seconds": timeout, "model": None, "questions": [],
    }
    done = {e["question"]: e for e in manifest["questions"]}
    for q in questions:
        entry = done.get(q["question"])
        qdir = root / q["question"]
        # 已有結果的題目接續時跳過：成功的，以及逾時／出錯的（那也是一個結果，不自動重跑；要補跑用 --retry-failed）。
        # 只有「額度用完所以根本沒跑」的題目會被補上。
        if entry and entry.get("run_id") and (qdir / "runs" / entry["run_id"] / "prediction.json").exists() \
                and (entry["status"] == "ok" or (entry["status"] in ("timeout", "error") and not retry_failed)):
            say(f"Q{q['id']} {q['question']}：已有 {entry['run_id']}（{entry['status']}），跳過")
            continue
        run_id = run_system.new_run_id(qdir / "runs")
        cmd = [sys.executable, str(EVAL / "run_system.py"), str(qdir / "gold.json"), "--run-id", run_id,
               "--live", "on" if live else "off", "--browser", "on" if browser else "off",
               "--label", f"{batch_dir.name} {label}".strip()]
        env = dict(os.environ, LIVE_LOG="info", LANGFUSE_TRACING_ENABLED="false")
        say(f"Q{q['id']} {q['question']}：開始（{run_id}，上限 {timeout} 秒）")
        res = runner(cmd, timeout, batch_dir / "logs" / f"Q{q['id']:02d}.log", env)
        run_dir = qdir / "runs" / run_id
        status = classify(res, run_dir)
        rec = {"id": q["id"], "question": q["question"], "run_id": run_id, "status": status, "elapsed_seconds": res["elapsed"], "at": _now()}
        if status == "quota":
            rec["run_id"] = None
            rec["note"] = "ollama 額度用完（402），這題沒有跑；整批停下，補額度後用 --resume 接著跑"
        elif status in ("timeout", "error"):
            write_failure_stub(run_dir, q, status, res, f"{batch_dir.name} {label}".strip(), git_state()["commit"], live, browser, timeout)
            rec["note"] = f"逾時（{timeout} 秒）" if status == "timeout" else f"出錯，結束碼 {res['returncode']}；見 logs/Q{q['id']:02d}.log"
        else:
            pred = _read(run_dir / "prediction.json") or {}
            manifest["model"] = manifest["model"] or pred.get("model")
            manifest["git"]["run_system_version"] = pred.get("system_version")
        done[q["question"]] = rec
        manifest["questions"] = [done[x["question"]] for x in load_questions(root=root) if x["question"] in done]
        _write(manifest_path, manifest)
        say(f"Q{q['id']} {q['question']}：{status}（{res['elapsed']} 秒）")
        if status == "quota":
            say("碰到 402，整批停下。")
            break
    return manifest


# ---------- 階段 A 之後：離線計分與總表 ----------
def score_offline(manifest: dict, root: Path = EVAL, say=print) -> list[dict]:
    """對每個成功的 run 做階段 2 計分與階段 3 的 prepare（都離線）。回傳每題一行的摘要。"""
    rows = []
    for e in manifest["questions"]:
        row = {"id": e["id"], "question": e["question"], "status": e["status"], "run_id": e.get("run_id"), "elapsed": e.get("elapsed_seconds")}
        if e["status"] == "ok":
            qdir = root / e["question"]
            run_dir = qdir / "runs" / e["run_id"]
            for step, cmd in (("score_programmatic", [sys.executable, str(EVAL / "score_programmatic.py"), str(qdir / "gold.json"), str(run_dir / "prediction.json")]),
                              ("stage3 prepare", [sys.executable, str(EVAL / "stage3.py"), "prepare", str(qdir / "gold.json"), str(run_dir)])):
                r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=dict(os.environ, LIVE_BROWSER="off"))
                if r.returncode != 0:
                    row["error"] = f"{step} 失敗：{(r.stderr or r.stdout)[-300:]}"
                    break
            pred = _read(run_dir / "prediction.json") or {}
            s2 = _read(run_dir / "scores.stage2.json") or {}
            row["answer_chars"] = len(pred.get("answer_body") or "")
            acc = s2.get("accuracy") or {}
            row["accuracy"] = f"{acc.get('hit')}/{acc.get('hard_keypoints')}" if acc else None
            row["rouge_f"] = (s2.get("rouge_l") or {}).get("f")
            row["context_sentence_p"] = ((s2.get("context") or {}).get("sentence") or {}).get("p")
        rows.append(row)
    return rows


def _metrics_version() -> str:
    import score_programmatic
    return score_programmatic.METRICS_VERSION


def write_summary(batch_dir: Path, manifest: dict, rows: list[dict]) -> Path:
    L = [f"# {manifest['batch_id']} 階段 A 摘要", "",
         f"- 開始：{manifest['created_at']}；live：{manifest['live']}；瀏覽器：{manifest['browser']}；單題上限：{manifest['timeout_seconds']} 秒",
         f"- 模型：{manifest.get('model')}；git：{manifest['git'].get('commit')}"
         f"{'（系統有未提交修改）' if manifest['git'].get('system_uncommitted') else ''}"
         f"{'（evaluation/ 有未提交修改）' if manifest['git'].get('evaluation_uncommitted') else ''}", "",
         "| 題 | 題目 | 狀態 | run | 耗時(秒) | 答案字數 | Accuracy(規則) | ROUGE-L F | Context 句子 P（字串比對，只供比較） |", "|---|---|---|---|---|---|---|---|---|"]

    def f(v):
        return "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))
    for r in rows:
        L.append(f"| Q{r['id']} | {r['question']} | {r['status']} | {f(r.get('run_id'))} | {f(r.get('elapsed'))} | {f(r.get('answer_chars'))} | "
                 f"{f(r.get('accuracy'))} | {f(r.get('rouge_f'))} | {f(r.get('context_sentence_p'))} |")
    L += ["", f"指標版本 {_metrics_version()}：Context 句子 Recall 要等階段 3 由 Claude 判斷「有沒有讀到」才算（階段 A 之後只有字串比對的 Precision）；此版本之前的 Context 數字不能與之後的直接比較。"]
    bad = [r for r in rows if r["status"] != "ok" or r.get("error")]
    if bad:
        L += ["", "## 需要你看的", ""]
        for r in bad:
            L.append(f"- Q{r['id']} {r['question']}：{r['status']}" + (f"；{r['error']}" if r.get("error") else ""))
    pending = [e for e in load_questions() if e["id"] not in {r["id"] for r in rows}]
    if pending:
        L += ["", "還沒跑：" + "、".join(f"Q{p['id']}" for p in pending)]
    L += ["", "下一步：停在這裡等使用者說「開始評測」並同意開子代理（階段 B，一題一題）。", ""]
    out = batch_dir / "summary.md"
    out.write_text("\n".join(L), encoding="utf-8")
    return out


# ---------- status ----------
def question_stage(qdir: Path, entry: dict | None) -> str:
    if not entry:
        return "未跑"
    if entry["status"] != "ok":
        return entry["status"]
    d = qdir / "runs" / entry["run_id"]
    for name, label in (("scores.json", "已算分（階段 3）"), ("judge.json", "已判斷，待驗證與算分"), ("trace.json", "已回推，待判斷"),
                        ("trace_input.json", "待回推（階段 B 還沒開始）"), ("scores.stage2.json", "已程式計分，待 prepare")):
        if (d / name).exists():
            return label
    return "只有 prediction"


def cmd_status(batch_id: str, root: Path = EVAL, batches: Path = BATCHES, say=print) -> int:
    m = _read(batches / batch_id / "manifest.json")
    if not m:
        say(f"找不到 {batches / batch_id / 'manifest.json'}")
        return 2
    by = {e["question"]: e for e in m["questions"]}
    for q in load_questions(root=root):
        e = by.get(q["question"])
        say(f"Q{q['id']:<2d} {q['short']:<10s} {question_stage(root / q['question'], e)}"
            + (f"（{e['run_id']}，{e['elapsed_seconds']} 秒）" if e and e.get("run_id") else ""))
    return 0


# ---------- export ----------
def cases_from_manifest(manifest: dict, root: Path = EVAL) -> dict:
    by = {e["question"]: e for e in manifest["questions"] if e.get("run_id")}
    cases = []
    for q in load_questions(root=root):
        e = by.get(q["question"])
        if not e:
            continue
        cases.append({"id": q["id"], "question": q["question"], "short": q["short"], "group": q["group"], "dir": f"runs/{e['run_id']}"})
    return {"note": f"{manifest['batch_id']}：真實 run（由 manifest 產生）", "cases": cases}


def live_observations(pred: dict) -> dict:
    """從 prediction 的 context 標記行整理現場讀取的痕跡：各狀態的頁數、轉址（mf／mv）。"""
    from urllib.parse import unquote
    states, moved = {}, []
    for c in pred.get("context") or []:
        for kvs, url in _MARKER_RE.findall(c.get("text") or ""):
            kv = dict(_KV_RE.findall(kvs))
            st = kv.get("status", "?")
            states[st] = states.get(st, 0) + 1
            if kv.get("mf") or kv.get("mv"):
                moved.append({"status": st, "url": url, "moved_from": unquote(kv.get("mf", "")), "moved_to": unquote(kv.get("mv", ""))})
    return {"states": states, "moved": moved}


def summary_table(batch_dir: Path, manifest: dict, root: Path = EVAL) -> list[str]:
    """每題一列的總表。有 cases_all.json（把別批的 run 補進來的 11 題清單，例如 Q1）就用它，否則用這批 manifest 的題目。"""
    import dashboard.export_scores as ex
    spec = _read(batch_dir / "cases_all.json") or cases_from_manifest(manifest, root)
    f = lambda x: "—" if x is None else f"{x:.2f}"
    L = ["## 總表", "",
         "| Q | 題目 | run | 狀態 | Completeness | Hallucination | Irrelevance | Sentence R | 有依據比例 | 規則 Accuracy | 不計分 |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    versions = set()
    for c in spec["cases"]:
        r = ex.build_row(c, root)
        acc, ev = r.get("accuracy"), r.get("evidence") or {}
        excl = "、".join(x["id"] for x in (r.get("responses") or {}).get("excluded") or []) or ""
        versions.add(r.get("metrics_version"))
        L.append(f"| {r['query']['query_id']} | {r['query']['short']} | {r['run_id'] or '—'} | {r['status']} | {f(r['completeness'])} | {f(r['hallucination'])} | "
                 f"{f(r['irrelevance'])} | {f(r['Sentences_Recall'])} | {f(ev.get('rate'))} | {(str(acc['hit']) + '/' + str(acc['total'])) if acc else '—'} | {excl} |")
    L += ["", f"- 每題用哪個 run、指標版本：{'、'.join(sorted(v for v in versions if v)) or '（沒有算分）'}；Q1 等不在這批 manifest 裡的題目來自 `cases_all.json`。"
          "各題的 run 不一定同一次跑（有重跑的題目用重跑的 run，見 manifest 的 reruns）。",
          "- 規則 Accuracy 與 Claude 判斷的 Completeness 是兩個獨立判斷；已知規則版有樓層與分機的誤判（議題 F34、F38），數字偏低。",
          "- 「不計分」欄是 gold 標了 excluded 的 keypoint（議題 F39），不進任何分母。", ""]
    return L


def write_report(batch_dir: Path, manifest: dict, root: Path = EVAL) -> Path:
    import dashboard.export_scores as ex  # noqa: F401  (確認匯出程式可 import)
    L = [f"# {manifest['batch_id']} 跨題報告", "",
         f"- live：{manifest['live']}；瀏覽器：{manifest['browser']}；模型：{manifest.get('model')}；git：{manifest['git'].get('commit')}"
         f"{'+uncommitted' if manifest['git'].get('system_uncommitted') else ''}；建立：{manifest['created_at']}",
         f"- 指標版本：{_metrics_version()}（Context 句子 Recall 由 Claude 判斷，不是字串比對；Sentence Precision 與 Words 指標仍是字串比對，Sentence F1 混合；此版本之前的 Context 數字不能直接比較）",
         "- 限制：每題只跑一次，LLM 有隨機性；現場頁面會隨時間變，`prediction.json` 是系統當時看到的唯一記錄；"
         "隔離回推是否真的隔離看每題 `trace.json` 的 judge 註記與稽核結果。", ""]
    rr = manifest.get("reruns")
    if rr:
        L += [f"- 重跑（{rr['at']}，{rr['after']} 修好之後，git {rr['git']}）：{'、'.join(rr['questions'])} 改用 run02，{rr['note']}", ""]
    L += summary_table(batch_dir, manifest, root)
    L += ["## 每題", ""]
    moved_all, state_all = [], {}
    for e in manifest["questions"]:
        qdir = root / e["question"]
        L.append(f"### Q{e['id']} {e['question']} — {e['status']}" + (f"（{e['run_id']}，{e['elapsed_seconds']} 秒）" if e.get("run_id") else ""))
        if e.get("note"):
            L.append(f"- {e['note']}")
        if e["status"] == "ok":
            d = qdir / "runs" / e["run_id"]
            pred = _read(d / "prediction.json") or {}
            sc = _read(d / "scores.json")
            s2 = _read(d / "scores.stage2.json")
            if sc:
                kp = sc.get("keypoint") or {}
                L.append(f"- 階段 3 已算分：Completeness {kp.get('completeness')}、Hallucination {kp.get('hallucination')}；"
                         f"漏斗 {json.dumps(sc.get('funnel'), ensure_ascii=False)[:300]}")
                for x in sc.get("excluded_keypoints", []):
                    L.append(f"- 不計分：{x['id']}（{x.get('issue')}，{x.get('reason')}；判 {x.get('judged')}）")
                for w in sc.get("warnings", []):
                    L.append(f"- warning：{w}")
                for dg in sc.get("disagreements", []):
                    L.append(f"- disagreement：{json.dumps(dg, ensure_ascii=False)[:300]}")
            elif s2:
                acc = s2.get("accuracy") or {}
                L.append(f"- 只有階段 2：Accuracy(規則) {acc.get('hit')}/{acc.get('hard_keypoints')}；階段 3 還沒做")
            obs = live_observations(pred)
            if obs["states"]:
                L.append("- 現場讀取：" + "、".join(f"{k}×{v}" for k, v in sorted(obs["states"].items())))
            for m in obs["moved"]:
                moved_all.append((e["id"], m))
                L.append(f"- 轉址：{m['status']}，{m['moved_from'] or m['url']} → {m['moved_to'] or m['url']}")
            for k, v in obs["states"].items():
                state_all[k] = state_all.get(k, 0) + v
        L.append("")
    L += ["## live 與轉址觀察（F19）", "",
          "- 全批現場讀取狀態：" + ("、".join(f"{k}×{v}" for k, v in sorted(state_all.items())) or "（沒有現場標記；live 可能沒開）"),
          "- 走到轉址的頁面：" + (f"{len(moved_all)} 個" if moved_all else "沒有（預期：只有第 1 題與提到出納組的第 8 題可能走到總務處人員頁）"),
          "- 渲染（Chromium）次數沒有寫進 prediction；要看見它，請讀 `logs/Qxx.log`（已開 `LIVE_LOG=info`）。", ""]
    out = batch_dir / "report.md"
    out.write_text("\n".join(L), encoding="utf-8")
    return out


def cmd_export(batch_id: str, root: Path = EVAL, batches: Path = BATCHES, say=print) -> int:
    from dashboard import export_scores
    bdir = batches / batch_id
    m = _read(bdir / "manifest.json")
    if not m:
        say(f"找不到 {bdir / 'manifest.json'}")
        return 2
    cases = cases_from_manifest(m, root)
    cpath = bdir / "cases.json"
    _write(cpath, cases)
    rows = export_scores.export(cpath, bdir / "dashboard.jsonl", root)
    rep = write_report(bdir, m, root)
    say(f"→ {bdir / 'dashboard.jsonl'}（{len(rows)} 題）\n→ {rep}")
    if (bdir / "cases_all.json").exists():
        all_rows = export_scores.export(bdir / "cases_all.json", bdir / "dashboard_all.jsonl", root)
        say(f"→ {bdir / 'dashboard_all.jsonl'}（{len(all_rows)} 題，含別批補進來的 run）")
    missing = [q for q in load_questions(root=root) if q["question"] not in {c['question'] for c in cases['cases']}]
    if missing:
        say("沒有 run 的題目（不在 jsonl 裡）：" + "、".join(f"Q{q['id']}" for q in missing))
    return 0


# ---------- CLI ----------
def _print_plan(qs, live, browser, timeout, errors, warnings, say=print):
    say(f"這批會依序跑 {len(qs)} 題：" + "、".join(f"Q{q['id']}" for q in qs))
    say(f"  live={'開（會對 nccu.edu.tw 送請求）' if live else '關（固定快照）'}；Chromium 渲染={'開' if browser else '關'}；單題上限 {timeout} 秒；每題只跑一次")
    say("  會呼叫 ollama（Gemma）；不呼叫 Claude、不開子代理")
    for w in warnings:
        say(f"[警告] {w}")
    for e in errors:
        say(f"[錯誤] {e}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        s = sub.add_parser(name)
        s.add_argument("--only", default=None, help="只跑這些題號，例如 1,2,5")
        s.add_argument("--live", choices=["on", "off"], default="on")
        s.add_argument("--browser", choices=["on", "off"], default=None, help="預設：live on 時開")
        s.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
        if name == "run":
            s.add_argument("--run", action="store_true", help="真的跑（呼叫 ollama；live on 時也會連 nccu.edu.tw）。沒有這個旗標只是預演")
            s.add_argument("--resume", default=None, metavar="BATCHNN", help="接續這個批次，跳過已成功的題目")
            s.add_argument("--label", default="")
            s.add_argument("--retry-failed", action="store_true", help="接續時連逾時、出錯的題目也重跑（預設不重跑）")
    sub.add_parser("status").add_argument("batch")
    sub.add_parser("export").add_argument("batch")
    a = ap.parse_args(argv)

    if a.cmd == "status":
        return cmd_status(a.batch)
    if a.cmd == "export":
        return cmd_export(a.batch)

    only = {int(x) for x in a.only.split(",")} if a.only else None
    qs = load_questions(only)
    live = a.live == "on"
    browser = (a.browser == "on") if a.browser else live
    errors, warnings = preflight(qs, live)
    _print_plan(qs, live, browser, a.timeout, errors, warnings)
    if errors:
        return 2
    if a.cmd == "plan" or not a.run:
        print("\n預演結束，沒有送出任何請求。要真的跑，請使用者明說後加 --run。")
        return 0

    batch_id = a.resume or new_batch_id(BATCHES)
    batch_dir = BATCHES / batch_id
    if a.resume and not (batch_dir / "manifest.json").exists():
        print(f"找不到 {batch_dir / 'manifest.json'}")
        return 2
    batch_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n批次 {batch_id} 開始")
    manifest = run_batch(batch_dir, qs, live, browser, a.timeout, label=a.label, retry_failed=a.retry_failed)
    rows = score_offline(manifest)
    print(f"摘要：{write_summary(batch_dir, manifest, rows)}")
    return 1 if any(e["status"] == "quota" for e in manifest["questions"]) else 0


if __name__ == "__main__":
    sys.exit(main())
