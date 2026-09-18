"""
rag/eval_criteria/leave_of_absence.py
休學 / 復學 / 休學+圖書館複合查詢的 eval criteria。
Split out of rag/eval.py (2026-09-18) — see rag/eval_criteria/__init__.py's
module docstring for why this package exists.

Changes from v1 (24 pts):
  - seven_stops  → nine_stamps  : 正確反映 QP-T01-03-02 表單的 9 個蓋章欄位；
                                   keywords 加入「組長」「教務長」；min_hits 提升至 7。
  - dean_approvals (NEW)        : 教務處內部需經組長批示 + 教務長核准兩層，明確驗證。
  - refund_table   min_hits 2→3 : 全額/2/3/1/3 三段均需出現，避免只提「退費」就得分。
  - contact_info   min_hits 2→3 : 要求涵蓋出納+教務+至少一個住宿/生僑/國合，共 3 支分機。
  - contact_persons: 加入「林啓屏」（教務長）；min_hits 1→2（需跨單位至少 2 人）。
  - pickup_method  min_hits 1→2 : 需同時提及「三個工作天」等時效 + 至少一種取件管道。
  - mental_health_note min_hits 1→2: 需同時提及身心健康中心名稱 + 電話或懷孕情境。

Changes (2026-08-25, Phase F Step 1 — real-world verification via office_contacts_index.jsonl):
  - dean_approvals / contact_persons: 「林啓屏」→「劉吉軒」。林啓屏已於本次驗證確認轉任副校長，
    現任教務長為劉吉軒（Step 0c的Playwright重爬office_contacts_index.jsonl直接證實）。
    王揚忠（註冊組組長）、盧誼甄、黃婉綝、陳哲良均確認仍在職、角色不變，不需更動。
    現行系統（office_lookup_skill.py等）仍硬編碼林啓屏，要到Step 3才會動態化修復——
    這代表Step 3完成前，這兩項criteria會刻意扣分，是「修正前基準」，不是bug。
"""

EVAL_CRITERIA = [
    {
        "name":        "process_first",
        "description": "以步驟清單格式回答，不以規定開頭",
        "keywords":    ["步驟", "第一步", "①", "第1步", "流程"],
        "min_hits":    1,
    },
    {
        "name":        "nine_stamps",
        "description": "9 個蓋章欄位完整：前 6 站（系所/圖書館/出納/住宿/生僑/國合）+ 教務處 3 層（承辦/組長/教務長）",
        "keywords":    ["系所", "圖書館", "出納", "住宿組", "生僑", "國際合作", "教務", "組長", "教務長"],
        # min_hits=9：9 個關鍵字全部出現才給滿分。
        # 舊值 7 的 bug：只需 7 個地點關鍵字（系所…教務）就能達標，
        # 不需要「組長」「教務長」——但這兩欄正是 9 欄與 7 站的關鍵差異。
        "min_hits":    9,
    },
    {
        "name":        "office_locations",
        "description": "每站有辦公室地點（行政大樓 X 樓）",
        "keywords":    ["行政大樓", "5樓", "3樓", "4樓", "8樓", "5 樓", "3 樓", "4 樓", "8 樓"],
        "min_hits":    3,
    },
    {
        "name":        "conditional_stops",
        "description": "住宿生 / 國際學生條件標注",
        "keywords":    ["住宿生", "國際學生"],
        "min_hits":    2,
    },
    {
        "name":        "dean_approvals",
        "description": "教務處需經組長批示及教務長核准（QP-T01-03-02 表單明列兩層核准）",
        # 2026-08-27: dropped 王揚忠/劉吉軒 — with all 4 keywords + min_hits=2,
        # "組長"+"王揚忠" (same person, the 組長 layer only) satisfied the
        # threshold without "教務長" ever appearing, silently passing
        # answers missing the second review layer entirely (the actual
        # thing this criterion is supposed to verify). Only the two role
        # words remain, so min_hits=2 now requires BOTH layers by
        # construction, not an OR-style pick-any-2 across a 4-item list.
        "keywords":    ["組長", "教務長"],
        "min_hits":    2,
    },
    {
        "name":        "refund_table",
        "description": "退費比例表存在（全額退費 + 2/3 + 1/3 三欄均出現；接受中文或 Arabic 分數格式）",
        "keywords":    ["全額退費", "2/3", "1/3", "三分之二", "三分之一", "退費"],
        "min_hits":    3,
    },
    {
        "name":        "contact_info",
        "description": "至少 3 個電話分機（出納 62123 + 教務 63279 + 住宿/生僑/國合至少一處）",
        "keywords":    ["62123", "63279", "62222", "63251", "62040", "分機"],
        "min_hits":    3,
    },
    {
        "name":        "form_links",
        "description": "QP-T01-03-02 休學申請書連結存在（必要）",
        "keywords":    ["QP-T01-03-02"],
        "min_hits":    1,
    },
    {
        "name":        "supplementary_forms",
        "description": "補充表單：QP-T01-02-05 委託書 或 QP-T01-03-04 提早復學",
        "keywords":    ["QP-T01-02-05", "QP-T01-03-04"],
        "min_hits":    1,
    },
    {
        "name":        "no_hallucination",
        "description": "無幻覺（人工確認，自動給滿分）",
        "keywords":    [],
        "min_hits":    0,
    },
    {
        "name":        "contact_persons",
        "description": "至少提及 2 位承辦人姓名（需涵蓋不同單位）",
        "keywords":    ["盧誼甄", "王揚忠", "黃婉綝", "陳哲良", "劉吉軒"],
        "min_hits":    2,
    },
    {
        "name":        "pickup_method",
        "description": "說明核准後至少 2 種領件方式（時效 + 管道）",
        "keywords":    ["三個工作天", "郵寄", "iNCCU", "領取"],
        "min_hits":    2,
    },
    {
        "name":        "mental_health_note",
        "description": "提及身心健康中心且附電話（8237-7419）或懷孕情境（至少 2 項）",
        "keywords":    ["身心健康中心", "8237-7419", "懷孕"],
        "min_hits":    2,
    },
]


# ── 復學辦理流程 Q&A evaluation ──────────────────────────────────────────────
# 9 criteria × 2 points = 18 max. Added 2026-08-25 (Phase F Step 1), gold
# standard sourced from aca.nccu.edu.tw's combined 休學/保留學籍/提早復學
# page + QP-T01-03-04 form text + office_contacts_index.jsonl.
#
# The single most important criterion here is `no_extra_dean_approval`:
# 復學 genuinely has a SHALLOWER approval chain than 休學 (registrar-section-
# head only, no 教務長 layer) — QP-T01-03-04's own "會辦單位蓋章" table has
# no 教務長 field, unlike QP-T01-03-02's explicit 組長→教務長 two-tier
# sign-off. If the system answers this by pattern-matching its 休學 prompt
# rules instead of reading this form's actual content, it will hallucinate
# a 教務長 approval step that doesn't exist here — exactly the generalization
# failure mode Phase F exists to catch (see CLAUDE.md "Phase E persistent
# failures" / phase_f_planning_report.md 6.x). Like `no_hallucination` this
# is scored full-marks by default and corrected on manual read of the answer.
EVAL_CRITERIA_RESUMPTION = [
    {
        "name":        "differentiates_scenarios",
        "description": "明確區分「期滿復學」（免表單，逕行完成註冊繳費）與「提早復學」（需表單+蓋章）兩種情境",
        "keywords":    ["期滿", "提早復學"],
        "min_hits":    2,
    },
    {
        "name":        "expiry_resumption_no_form",
        "description": "期滿復學：依規定期限完成註冊繳費即可，不需另外送件",
        "keywords":    ["依規定期限", "註冊", "繳費"],
        "min_hits":    2,
    },
    {
        "name":        "early_resumption_form",
        "description": "提早復學需填具 QP-T01-03-04 提早復學申請書",
        "keywords":    ["QP-T01-03-04", "提早復學申請書"],
        "min_hits":    1,
    },
    {
        "name":        "early_resumption_chain",
        "description": "提早復學蓋章鏈：系所會辦、生僑組、國際合作事務處、註冊組（至少 3 站）",
        "keywords":    ["系所", "生僑組", "國際合作", "註冊組"],
        "min_hits":    3,
    },
    {
        "name":        "conditional_notes",
        "description": "蓋章條件標注：生僑組僅男生及僑生需辦理、國際合作事務處僅國際學生需辦理",
        "keywords":    ["男生", "僑生", "國際學生"],
        "min_hits":    2,
    },
    {
        "name":        "contact_person",
        "description": "提及註冊組承辦窗口（組長王揚忠，經 office_contacts_index.jsonl 確認現任）",
        "keywords":    ["王揚忠", "註冊組組長"],
        "min_hits":    1,
    },
    {
        "name":        "office_location",
        "description": "提及辦公室樓層（生僑組行政大樓 3 樓、註冊組 4 樓）",
        "keywords":    ["行政大樓", "3樓", "4樓", "3 樓", "4 樓"],
        "min_hits":    2,
    },
    {
        "name":        "no_extra_dean_approval",
        "description": "無虛構教務長核准層——提早復學只需註冊組組長核准，QP-T01-03-04 表單本身沒有教務長欄位（人工確認，自動給滿分）",
        "keywords":    [],
        "min_hits":    0,
    },
    {
        "name":        "no_hallucination",
        "description": "無幻覺（人工確認，自動給滿分）",
        "keywords":    [],
        "min_hits":    0,
    },
]


# ── 複合查詢：休學 + 圖書館電話 Q&A evaluation ───────────────────────────────
# Added 2026-09-13. Gold standard 來源：Phase F Step 1 baseline
# (docs/phase_f_step1_eval_baseline.md Q6，2026-08-25 人工查證版本，proto3_langgraph
# 上實測 14/26——休學那半被複合查詢稀釋，7 站蓋章鏈只剩 3 站，form_links/
# conditional_stops/pickup_method/supplementary_forms 全部歸零。agentic_rag.py 改用
# multi_sub_query_node 拆成獨立子查詢後，Migration Step 10 regression 驗證兩邊皆正確
# 且互不污染，見 CLAUDE.md「如何辦理休學，圖書館的電話是多少」一列)。
#
# 只適用於這一組固定的複合查詢配對，不是通用複合查詢評分機制——直接沿用完整的
# EVAL_CRITERIA（休學半邊）+ 圖書館電話 2 項，兩邊都拿到滿分才代表複合查詢真正
# 沒有互相稀釋。
# 13 (休學) + 2 (圖書館) = 15 criteria × 2 = 30 max.
EVAL_CRITERIA_COMPOUND_LEAVE_LIBRARY = EVAL_CRITERIA + [
    {
        "name":        "library_main_line",
        "description": "圖書館總機（(02)2939-3091）或總圖分機 63222",
        "keywords":    ["2939-3091", "29393091", "63222"],
        "min_hits":    1,
    },
    {
        "name":        "library_branch_extensions",
        "description": "至少一個分館分機（50107/84006/67152 等）",
        "keywords":    ["50107", "84006", "67152"],
        "min_hits":    1,
    },
]
