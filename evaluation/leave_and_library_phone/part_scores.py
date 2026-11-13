"""
evaluation/leave_and_library_phone/part_scores.py

複合題把兩部分分開看：A（休學流程，K1–K60，匯入第 5 題）與 B（圖書館電話，K61 起）各自的 Completeness／Wrong／Irrelevant
（每個 keypoint 一個 part 欄位）。讀 gold.json 與一個 run 資料夾的 judge.json，不上網、不呼叫 LLM。不適用的 keypoint 不計入分母，與 stage3 相同。

用法（專案根目錄）：
  python evaluation/leave_and_library_phone/part_scores.py evaluation/leave_and_library_phone/tests/pipeline_setup/complete
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def part_scores(gold: dict, judge: dict) -> dict:
    parts = {k["id"]: k.get("part", "?") for k in gold["keypoints"]}
    out: dict[str, dict] = {}
    for j in judge["keypoints"]:
        p = out.setdefault(parts[j["id"]], {"relevant": 0, "wrong": 0, "irrelevant": 0, "not_applicable": 0})
        p[j["verdict"]] += 1
    for p in out.values():
        n = p["relevant"] + p["wrong"] + p["irrelevant"]
        p["total"] = n
        p["completeness"] = round(p["relevant"] / n, 3) if n else None
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    run = Path(argv[1])
    gold = json.loads((HERE / "gold.json").read_text(encoding="utf-8"))
    res = part_scores(gold, json.loads((run / "judge.json").read_text(encoding="utf-8")))
    for part, p in sorted(res.items()):
        name = {"A": "休學流程", "B": "圖書館電話"}.get(part, part)
        print(f"{part}（{name}）：Completeness {p['completeness']}  relevant {p['relevant']} / wrong {p['wrong']} / irrelevant {p['irrelevant']} / 不適用 {p['not_applicable']}（分母 {p['total']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
