"""
rag/eval_criteria/double_major_minor.py
碩博士班雙主修輔系申請 Q&A evaluation（跨處室 — 三段連續審核模式）.

Added 2026-09-18. Gold standard 來源：docs/upper_bound/Question003_double_major_minor.md
（Sonnet 直接讀 output/aca/extracted_supplementary.jsonl 裡 QP-T01-03-08
表單原文查證，非查記憶）。

這是這批「跨處室」criteria 的第三種架構模式：三段連續審核——所屬學系(原系所)
→ 申請學系(目標系所) → 教務處註冊組，三個單位依序簽核，比 dept_transfer.py
的兩系所並行模式多了一段，且教務處那段本身也是兩層（承辦人+組長）。跟
dorm_checkout.py 的鏈式依賴不同，這裡三段彼此是「依序審核同一份表格的不同
欄位」，不是「用前一站的結果才能辦下一站」。
6 criteria × 2 points = 12 max.
"""

EVAL_CRITERIA_DOUBLE_MAJOR_MINOR = [
    {
        "name":        "origin_dept_approval",
        "description": "所屬學系(原系所)是否同意所屬學生申請修讀雙主修/輔系",
        "keywords":    ["所屬學系", "原系所", "原學系"],
        "min_hits":    1,
    },
    {
        "name":        "target_dept_approval",
        "description": "申請學系(目標系所)是否准予修讀，適用規定必修/輔系科目表",
        "keywords":    ["申請學系", "擬修讀學系", "目標系所"],
        "min_hits":    1,
    },
    {
        "name":        "registrar_review",
        "description": "教務處註冊組承辦人+組長雙層審查基本資格（同 dean_approvals/dept_transfer 的修法——角色詞缺一不可，不能只挑兩個；2026-09-18 實測修正：接受「承辦」而非只認「承辦人」，答案用「行政承辦窗口」這種變化用法時也算數）",
        "keywords":    ["註冊組", "承辦人", "承辦", "組長"],
        "min_hits":    3,
    },
    {
        "name":        "application_window",
        "description": "碩博士班學生自註冊在學第二學期起至第四學期止可申請",
        "keywords":    ["第二學期", "第四學期"],
        "min_hits":    2,
    },
    {
        "name":        "no_reapply_rule",
        "description": "核定修讀後視同自願放棄原有雙主修/輔系資格，且不得再申請回復",
        "keywords":    ["視同自願放棄", "不得再申請回復"],
        "min_hits":    1,
    },
    {
        "name":        "no_hallucination",
        "description": "無幻覺（人工確認，自動給滿分）",
        "keywords":    [],
        "min_hits":    0,
    },
]
