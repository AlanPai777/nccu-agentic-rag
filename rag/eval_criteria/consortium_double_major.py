"""
rag/eval_criteria/consortium_double_major.py
台灣聯合大學系統跨校雙主修/輔系申請 Q&A evaluation（跨處室 — 跨機構模式）.

Added 2026-09-18. Gold standard 來源：docs/upper_bound/Question005_consortium_double_major.md
（Sonnet 直接讀 output/aca/extracted_supplementary.jsonl 裡 QP-T01-04-21
表單原文查證，非查記憶）。

這是這批「跨處室」criteria 的第五種架構模式：跨機構——不是同一所學校內部
的不同處室，而是橫跨政大與台聯大體系另一所學校（中央/清華/陽明交通），
兩校各自都有「主修/加修學系」+「註冊組」兩層簽核，結構上是
dept_transfer.py（並行雙處室）的機構層級放大版：不是兩個系所並列，是兩個
「學校」各自的完整簽核鏈並列。
7 criteria × 2 points = 14 max.
"""

EVAL_CRITERIA_CONSORTIUM_DOUBLE_MAJOR = [
    {
        "name":        "origin_school_approval",
        "description": "原就讀學校（政大）主修學系是否同意學生加修他校輔系/雙主修",
        "keywords":    ["原就讀學校", "主修學系"],
        "min_hits":    1,
    },
    {
        "name":        "target_school_approval",
        "description": "加修學校加修學系是否准予修讀，適用規定必修科目表",
        "keywords":    ["加修學校", "加修學系"],
        "min_hits":    1,
    },
    {
        "name":        "registrar_both_sides",
        "description": "兩校流程都要送各自註冊組承辦人+組長審查",
        "keywords":    ["註冊組", "承辦人", "組長"],
        "min_hits":    3,
    },
    {
        "name":        "consortium_schools",
        "description": "台聯大體系另一所學校名稱（中央/清華/陽明交通，至少提及 2 所，不需窮舉全部）",
        "keywords":    ["中央大學", "清華大學", "陽明交通大學"],
        "min_hits":    2,
    },
    {
        "name":        "quota_limit",
        "description": "跨校修讀輔系/雙主修上限（含校內）為一個雙主修及二個輔系",
        "keywords":    ["一個雙主修", "二個輔系"],
        "min_hits":    2,
    },
    {
        "name":        "auto_forfeit_rule",
        "description": "外校雙主修或輔系申請通過，即自願自動放棄現正修習之同類資格",
        "keywords":    ["自願自動放棄", "自動放棄"],
        "min_hits":    1,
    },
    {
        "name":        "no_hallucination",
        "description": "無幻覺（人工確認，自動給滿分）",
        "keywords":    [],
        "min_hits":    0,
    },
]
