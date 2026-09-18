"""
rag/eval_criteria/dept_transfer.py
碩士班轉系所 Q&A evaluation（跨處室 — 並行雙處室模式）.

Added 2026-09-18. Gold standard 來源：docs/upper_bound/Question001_dept_transfer.md
（Sonnet 直接讀 output/aca/extracted_supplementary.jsonl 裡 QP-T01-05-05
表單原文查證，非查記憶）。

這是這批「跨處室」criteria 的第一種架構模式：並行雙處室——同一張表單上同時印了
「原就讀系所主管審核意見」與「擬轉入就讀系所主管審核意見」兩個獨立欄位，兩個系所
互不依賴、可以任何順序核章，agent 只要讀到這張表格就能一次看到兩個處室，不需要
理解先後順序。跟 dorm_checkout.py 的「鏈式依賴」模式（第二站要靠第一站的結果才
查得到）是刻意設計成不同的失敗模式，用來分別驗證 resource_node 的靜態表格抽取
能力，以及 agent_node 多輪工具呼叫在有先後依賴時的穩定度。
6 criteria × 2 points = 12 max.
"""

EVAL_CRITERIA_DEPT_TRANSFER = [
    {
        "name":        "origin_dept_approval",
        "description": "提及原就讀系所主管審核（同意/不同意轉出）",
        "keywords":    ["原系所", "原就讀系所"],
        "min_hits":    1,
    },
    {
        "name":        "target_dept_approval",
        "description": "提及擬轉入系所主管審核（同意/不同意轉入）",
        "keywords":    ["轉入系所", "擬轉入系所", "轉入之系所"],
        "min_hits":    1,
    },
    {
        "name":        "registrar_three_layer",
        "description": "教務處三層審核：註冊組承辦人、註冊組組長、教務長（同 nine_stamps 的 dean_approvals 修法——三個角色詞都要出現，不能只挑兩個）",
        "keywords":    ["承辦人", "組長", "教務長"],
        "min_hits":    3,
    },
    {
        "name":        "application_window",
        "description": "轉系所申請期間：上學期 12月1日至12月31日，或下學期 6月1日至6月30日（需完整一組起訖日期，不能只有片段日期）",
        "keywords":    ["12月1日", "12月31日", "6月1日", "6月30日"],
        "min_hits":    2,
    },
    {
        "name":        "one_time_limit",
        "description": "碩士班轉所以一次為限",
        "keywords":    ["以一次為限"],
        "min_hits":    1,
    },
    {
        "name":        "no_hallucination",
        "description": "無幻覺（人工確認，自動給滿分）",
        "keywords":    [],
        "min_hits":    0,
    },
]
