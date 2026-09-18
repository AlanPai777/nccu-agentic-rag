"""
rag/eval_criteria/leave_form_download.py
休學申請表下載連結 Q&A evaluation（RESOURCE）. Split out of rag/eval.py (2026-09-18).

Added 2026-09-13. Gold standard 來源：Phase F Step 1 baseline
(docs/phase_f_step1_eval_baseline.md Q4，2026-08-25 人工查證版本，proto3_langgraph
上實測「失敗」——router 當時沒有 RESOURCE 分類，誤判成 PROCEDURE，通篇沒有下載
連結。agentic_rag.py 的 resource_node 已於 Migration Step 10 regression 驗證修復，
見 CLAUDE.md「休學申請表在哪裡下載」一列）。
3 criteria × 2 points = 6 max.
"""

EVAL_CRITERIA_LEAVE_FORM_DOWNLOAD = [
    {
        "name":        "form_id_correct",
        "description": "正確表單編號 QP-T01-03-02",
        "keywords":    ["QP-T01-03-02"],
        "min_hits":    1,
    },
    {
        "name":        "download_link_present",
        "description": "附上 moltke 下載連結，不是只提表單名稱",
        "keywords":    ["moltke.nccu.edu.tw"],
        "min_hits":    1,
    },
    {
        "name":        "no_hallucination",
        "description": "無幻覺，且不是整套辦理流程說明——RESOURCE 類問題要直接給連結（人工確認，自動給滿分）",
        "keywords":    [],
        "min_hits":    0,
    },
]
