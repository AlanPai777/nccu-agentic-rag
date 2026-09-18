"""
rag/eval_criteria/dorm_checkout.py
搬離宿舍如何辦理退還住宿保證金 Q&A evaluation（跨處室 — 鏈式依賴模式）.

Added 2026-09-18. Gold standard 來源：docs/upper_bound/Question002_dorm_checkout.md
（Sonnet 直接讀 output/osa/extracted_texts.jsonl 裡「退離宿程序」頁面原文
+ QP-M03-01-05 查證，非查記憶）。

Query 於 2026-09-18 重新設計：原本用的「如何辦理退宿」天生模糊，對應兩種
互斥的合法情境（學期前取消續住 vs. 學期中/末搬離退保證金），實測發現
agent 找到「學期前退宿」（QP-M03-01-04）候選就直接收斂作答，從未探索保證金
退還這條分支——這本身是個真實發現（KNOWLEDGE 路徑找到第一個候選就停，見
CLAUDE.md Known issues），但代表這個 query 測不準我們真正想測的鏈式依賴，
已改記錄在 docs/upper_bound/evaluation.md 的「模糊查詢」欄位，不再掛在
QUERY_CRITERIA_MAP 上。新 query 直接指名「保證金」，只對應
QP-M03-01-05 這一種情境。

這是這批「跨處室」criteria 的第二種架構模式：鏈式依賴——「持已在宿舍服務台簽章
的表格，三天內到住宿組辦理」，第二站（住宿組）要用第一站（宿舍服務台）簽過章的
同一張表才能辦，是敘述性的先後順序，不是像 dept_transfer.py 那樣印在同一張表格
上的並列欄位。這個查詢刻意跟休學無關（不是 QP-T01-xx 系列），用來驗證系統是否
能從一般行政頁面的敘述文字（而非表格結構）正確重建跨處室的先後依賴，不是只靠
resource_node 抓表單本身就能答對。
6 criteria × 2 points = 12 max.
"""

EVAL_CRITERIA_DORM_CHECKOUT = [
    {
        "name":        "dorm_desk_checkin",
        "description": "離宿需先辦理寢室檢查（2026-09-18 實測修正：QP-M03-01-05 表單本文用的是「宿舍區管理人員檢查寢室」，不是「退離宿程序」頁面用的「宿舍服務台」——agent 忠實引用它實際抓到的那份表單原文，兩種說法都對，keywords 需要都接受）",
        "keywords":    ["宿舍服務台", "服務台", "宿舍區管理人員", "檢查寢室", "寢室檢查"],
        "min_hits":    1,
    },
    {
        "name":        "housing_office_deadline",
        "description": "檢查後三天內持表至住宿組辦理（鏈式依賴的第二站，需同時提及時效與單位；2026-09-18 實測修正：接受「3天內」等阿拉伯數字格式，同 refund_table 接受「2/3」與「三分之二」兩種格式的既有做法）",
        "keywords":    ["三天內", "3天內", "3 天內", "住宿組"],
        "min_hits":    2,
    },
    {
        "name":        "required_documents",
        "description": "需檢附宿費繳費收據或住宿保證金相關文件",
        "keywords":    ["宿費繳費收據", "住宿保證金"],
        "min_hits":    1,
    },
    {
        "name":        "international_student_note",
        "description": "僑生/外籍生退保證金需另填委託書匯入代領人帳戶（條件標注，同休學 conditional_stops 的設計精神）",
        "keywords":    ["僑生", "外籍生", "代領人"],
        "min_hits":    2,
    },
    {
        "name":        "form_id",
        "description": "正確表單編號 QP-M03-01-05（離宿暨退還住宿保證金申請表）——query 已明確指名保證金，不該答成 QP-M03-01-04",
        "keywords":    ["QP-M03-01-05"],
        "min_hits":    1,
    },
    {
        "name":        "no_hallucination",
        "description": "無幻覺（人工確認，自動給滿分）",
        "keywords":    [],
        "min_hits":    0,
    },
]
