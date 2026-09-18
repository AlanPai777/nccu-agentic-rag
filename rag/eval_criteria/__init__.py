"""
rag/eval_criteria/
Per-query gold-standard criteria sets for rag/eval.py's scoring framework.

Split out of a single rag/eval.py (2026-09-18) once the file grew past 6
criteria sets and kept growing — each set carries a lengthy rationale
comment (why this keyword, why this min_hits, what bug it fixes), and
scrolling through one growing file to find/edit a single query's criteria
was getting unwieldy. Mirrors the pattern already used elsewhere in this
project for splitting by responsibility (rag/agentic/nodes/,
rag/agentic/logic/): one file per query family, this __init__.py just
aggregates them. rag/eval.py keeps score_answer()/print_score_report()
(the scoring logic) and re-exports everything here so agentic_rag.py's
`from rag.eval import print_score_report, QUERY_CRITERIA_MAP,
EVAL_CRITERIA` import keeps working unchanged.
"""

from rag.eval_criteria.leave_of_absence import (
    EVAL_CRITERIA,
    EVAL_CRITERIA_RESUMPTION,
    EVAL_CRITERIA_COMPOUND_LEAVE_LIBRARY,
)
from rag.eval_criteria.course_limit import EVAL_CRITERIA_COURSE_LIMIT
from rag.eval_criteria.leave_form_download import EVAL_CRITERIA_LEAVE_FORM_DOWNLOAD
from rag.eval_criteria.cashier_contact import EVAL_CRITERIA_CASHIER_CONTACT
from rag.eval_criteria.dept_transfer import EVAL_CRITERIA_DEPT_TRANSFER
from rag.eval_criteria.dorm_checkout import EVAL_CRITERIA_DORM_CHECKOUT
from rag.eval_criteria.double_major_minor import EVAL_CRITERIA_DOUBLE_MAJOR_MINOR
from rag.eval_criteria.exchange_credit_exemption import EVAL_CRITERIA_EXCHANGE_CREDIT_EXEMPTION
from rag.eval_criteria.consortium_double_major import EVAL_CRITERIA_CONSORTIUM_DOUBLE_MAJOR

# ── 查詢字串 → criteria 對照表 ───────────────────────────────────────────────
# 刻意用「一模一樣的查詢字串」對應，不是用 plan_node 的 query_type 分類結果
# 對應——這些 criteria 本來就是針對特定一題手動查證出來的 gold standard，不是
# 針對「這一類」問題的通用評分表。若改用 query_type 挑選，plan_node 分類錯的
# 時候評分也會跟著用錯 criteria，會把「這題答案對不對」跟「plan_node 分類準
# 不準」這兩件本該獨立判斷的事混在一起，汙染評分結果本身的可信度。
# CLI（agentic_rag.py）拿使用者輸入的原始查詢字串精確比對這份表；沒有命中的
# 查詢一律 fall back 回預設的 EVAL_CRITERIA（休學），維持既有行為不變。
QUERY_CRITERIA_MAP: dict[str, list[dict]] = {
    "如何辦理休學":                    EVAL_CRITERIA,
    "如何辦理復學":                    EVAL_CRITERIA_RESUMPTION,
    "選課上限幾學分":                  EVAL_CRITERIA_COURSE_LIMIT,
    "休學申請表在哪裡下載":            EVAL_CRITERIA_LEAVE_FORM_DOWNLOAD,
    "出納組電話幾號":                  EVAL_CRITERIA_CASHIER_CONTACT,
    "出納組的電話是幾號":              EVAL_CRITERIA_CASHIER_CONTACT,  # baseline 文件原始措辭，別名
    "如何辦理休學，圖書館的電話是多少": EVAL_CRITERIA_COMPOUND_LEAVE_LIBRARY,
    "碩士班轉系所需要經過哪些單位同意": EVAL_CRITERIA_DEPT_TRANSFER,
    "搬離宿舍如何辦理退還住宿保證金":  EVAL_CRITERIA_DORM_CHECKOUT,
    "碩士班雙主修輔系申請需要經過哪些單位審核": EVAL_CRITERIA_DOUBLE_MAJOR_MINOR,
    "出國交換學分抵免，體育、通識、外文通識課程分別要送哪個單位審核": EVAL_CRITERIA_EXCHANGE_CREDIT_EXEMPTION,
    "政大學生跨校修讀台聯大雙主修需要經過哪些單位審核": EVAL_CRITERIA_CONSORTIUM_DOUBLE_MAJOR,
}

__all__ = [
    "EVAL_CRITERIA",
    "EVAL_CRITERIA_RESUMPTION",
    "EVAL_CRITERIA_COMPOUND_LEAVE_LIBRARY",
    "EVAL_CRITERIA_COURSE_LIMIT",
    "EVAL_CRITERIA_LEAVE_FORM_DOWNLOAD",
    "EVAL_CRITERIA_CASHIER_CONTACT",
    "EVAL_CRITERIA_DEPT_TRANSFER",
    "EVAL_CRITERIA_DORM_CHECKOUT",
    "EVAL_CRITERIA_DOUBLE_MAJOR_MINOR",
    "EVAL_CRITERIA_EXCHANGE_CREDIT_EXEMPTION",
    "EVAL_CRITERIA_CONSORTIUM_DOUBLE_MAJOR",
    "QUERY_CRITERIA_MAP",
]
