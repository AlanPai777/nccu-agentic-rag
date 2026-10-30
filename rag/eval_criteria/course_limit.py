"""
rag/eval_criteria/course_limit.py
選課學分上限 Q&A evaluation. Split out of rag/eval.py (2026-09-18).

Added 2026-09-13. Gold standard 來源：Phase F Step 1 baseline
(Phase F 基準筆記 Q5，2026-08-25 人工查證版本，proto3_langgraph
上實測「完美」)。依政大學則第十五條：學士班第一至三學年每學期不得少於12學分、
不得多於25學分；第四學年不得少於10學分、不得多於25學分；經系主任核可可超修/
減修，至多以6學分為限；碩、博士班由各系（所）自定，無統一規定。
5 criteria × 2 points = 10 max.
"""

EVAL_CRITERIA_COURSE_LIMIT = [
    {
        "name":        "undergrad_upper_bound",
        "description": "學士班上限 25 學分（第一至四學年皆適用）",
        "keywords":    ["25學分", "25 學分"],
        "min_hits":    1,
    },
    {
        "name":        "undergrad_lower_bound",
        "description": "學士班下限：第一至三學年 12 學分、第四學年 10 學分",
        "keywords":    ["12學分", "12 學分", "10學分", "10 學分"],
        "min_hits":    2,
    },
    {
        "name":        "overload_limit",
        "description": "經系主任核可超修/減修，至多以 6 學分為限",
        "keywords":    ["6學分", "6 學分", "超修", "系主任"],
        "min_hits":    2,
    },
    {
        "name":        "grad_no_uniform_rule",
        "description": "碩、博士班修課學分由各系（所）自定，無統一規定",
        "keywords":    ["碩士班", "博士班", "系所自定", "系（所）自定", "無統一規定"],
        "min_hits":    2,
    },
    {
        "name":        "no_hallucination",
        "description": "無幻覺（人工確認，自動給滿分）",
        "keywords":    [],
        "min_hits":    0,
    },
]
