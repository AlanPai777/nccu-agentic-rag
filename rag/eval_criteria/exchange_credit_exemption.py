"""
rag/eval_criteria/exchange_credit_exemption.py
出國/國內交換選課學分抵免 Q&A evaluation（跨處室 — 條件分岔模式）.

Added 2026-09-18. Gold standard 來源：docs/upper_bound/Question004_exchange_credit_exemption.md
（Sonnet 直接讀 output/aca/extracted_supplementary.jsonl 裡 QP-T01-04-05
表單原文查證，非查記憶）。

這是這批「跨處室」criteria 的第四種架構模式：條件分岔——審核單位不是固定
順序，而是依「科目類型」分岔到不同處室（體育→體育室、通識→通識教育中心、
外文通識→外文中心、雙主修/輔系→輔雙學系），全部審查完才送教務處核定。跟
dept_transfer.py 的並行雙處室、dorm_checkout.py 的鏈式依賴、
double_major_minor.py 的三段連續審核都不同，測的是 agent 能不能正確重建
「不同條件對應不同單位」這種分支結構，而不是單純的線性/並行流程。
7 criteria × 2 points = 14 max.
"""

EVAL_CRITERIA_EXCHANGE_CREDIT_EXEMPTION = [
    {
        "name":        "pe_office",
        "description": "抵免科目為體育課程時，送體育室審定",
        "keywords":    ["體育室"],
        "min_hits":    1,
    },
    {
        "name":        "gecenter_office",
        "description": "抵免科目為一般通識課程時，送通識教育中心審定",
        "keywords":    ["通識教育中心"],
        "min_hits":    1,
    },
    {
        "name":        "language_center_office",
        "description": "抵免科目為外文通識時，送外文中心審定",
        "keywords":    ["外文中心"],
        "min_hits":    1,
    },
    {
        "name":        "registrar_final_approval",
        "description": "各單位審查後仍需送教務處核定，才登錄成績總表",
        "keywords":    ["教務處", "核定"],
        "min_hits":    2,
    },
    {
        "name":        "credit_limit",
        "description": "抵免學分上限：博碩士生二分之一、學士班三分之一（畢業最低學分總數）（2026-09-18 實測修正：原本只認「二分之一」「三分之一」會被「三分之一基準日」這個申請期限用語誤判命中——同一份文件「抵免上限」跟「申請期限」兩件事剛好共用「三分之一」這個子字串，改用完整片語避免跟 application_deadline 撞字）",
        "keywords":    ["畢業最低學分總數二分之一", "畢業最低學分總數三分之一", "二分之一為限", "三分之一為限"],
        "min_hits":    1,
    },
    {
        "name":        "application_deadline",
        "description": "於次學期三分之一基準日前向就讀系辦理抵免申請",
        "keywords":    ["基準日"],
        "min_hits":    1,
    },
    {
        "name":        "no_hallucination",
        "description": "無幻覺（人工確認，自動給滿分）",
        "keywords":    [],
        "min_hits":    0,
    },
]
