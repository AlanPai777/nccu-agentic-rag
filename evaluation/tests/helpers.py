"""
evaluation/tests/helpers.py — 評測程式測試共用的小工具（路徑、讀檔、在暫存目錄跑 CLI）。

從專案根目錄執行：
  python -m unittest discover -s evaluation/tests -v
"""
import json
import os
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
EVAL = TESTS.parent
ROOT = EVAL.parent
FIX = TESTS / "fixtures"
GOLD = EVAL / "cashier_contact" / "gold.json"
TAMPER = EVAL / "cashier_contact" / "tests" / "tampered_v1"

if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

# 測試不能連到 Chromium 與 Langfuse（CLAUDE.md：跑測試要 LIVE_BROWSER=off）
os.environ["LIVE_BROWSER"] = "off"
os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")


def read(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, obj) -> None:
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cli(script: str, *args) -> subprocess.CompletedProcess:
    """在專案根目錄跑 evaluation/<script>，回傳 CompletedProcess（不丟例外，由測試自己檢查結束碼）。"""
    return subprocess.run([sys.executable, str(EVAL / script), *map(str, args)], cwd=ROOT,
                          capture_output=True, text=True, env=dict(os.environ))


def build_run(tmp: Path, *, prediction: dict, trace_input=None, trace: dict, judge: dict, prepare: bool = False) -> Path:
    """在 tmp 底下造一個 run 資料夾。prepare=True 時由 `stage3 prepare` 產生 trace_input.json（也順便測了 prepare）。"""
    write(tmp / "prediction.json", prediction)
    if prepare:
        r = cli("stage3.py", "prepare", GOLD, tmp)
        assert r.returncode == 0, r.stderr
    else:
        write(tmp / "trace_input.json", trace_input)
    write(tmp / "trace.json", trace)
    write(tmp / "judge.json", judge)
    r = cli("score_programmatic.py", GOLD, tmp / "prediction.json")
    assert r.returncode == 0, r.stderr
    return tmp


def score(tmp: Path) -> dict:
    r = cli("stage3.py", "score", GOLD, tmp)
    assert r.returncode == 0, r.stdout + r.stderr
    return read(tmp / "scores.json")
