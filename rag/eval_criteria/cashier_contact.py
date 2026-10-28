"""
rag/eval_criteria/cashier_contact.py
出納組電話 Q&A evaluation（CONTACT）. Split out of rag/eval.py (2026-09-18).

Added 2026-09-13. Gold standard 來源：Phase F Step 1 baseline
(Phase F 基準筆記 Q3，2026-08-25 人工查證版本，proto3_langgraph
上實測「正確」)。出納組沒有單一代表號，官方公布的合法分機範圍是
62119-62123、62125-62127、62172、62173（來源：cscr subdomain 繳費須知頁）；
62120（劉桂芬組長）是官網 footer 實際使用的代表號，62123（余淑娟）是範圍內另一
個合法分機。

刻意不把承辦人姓名列為必要 keyword——這份 baseline 文件自己記錄過教訓：教務長
「林啓屏→劉吉軒」人事異動時，若 criteria 認姓名而非角色詞/分機，答案會隨人事
變動而失真，且需要每次異動手動維護。分機範圍相對姓名更穩定，作為主要判準。
2 criteria × 2 points = 4 max.
"""

EVAL_CRITERIA_CASHIER_CONTACT = [
    {
        "name":        "extension_in_range",
        "description": "分機屬於官方合法範圍（62119-62123、62125-62127、62172、62173 之一）",
        "keywords":    ["62119", "62120", "62121", "62122", "62123",
                         "62125", "62126", "62127", "62172", "62173"],
        "min_hits":    1,
    },
    {
        "name":        "office_name_present",
        "description": "答案明確提及「出納組」",
        "keywords":    ["出納組"],
        "min_hits":    1,
    },
]
