"""
rag/eval.py
Auto-scoring framework for NCCU academic-affairs Q&A evaluation.

Scoring logic only (score_answer/print_score_report) — the actual per-query
gold-standard criteria sets live in rag/eval_criteria/ (split out 2026-09-18,
see that package's __init__.py docstring for why). Re-exports
EVAL_CRITERIA/QUERY_CRITERIA_MAP so existing imports
(`from rag.eval import print_score_report, QUERY_CRITERIA_MAP,
EVAL_CRITERIA` in agentic_rag.py / rag/proto1_direct.py) keep working
unchanged.
"""

from rag.eval_criteria import (
    EVAL_CRITERIA,
    EVAL_CRITERIA_RESUMPTION,
    EVAL_CRITERIA_COMPOUND_LEAVE_LIBRARY,
    EVAL_CRITERIA_COURSE_LIMIT,
    EVAL_CRITERIA_LEAVE_FORM_DOWNLOAD,
    EVAL_CRITERIA_CASHIER_CONTACT,
    EVAL_CRITERIA_DEPT_TRANSFER,
    EVAL_CRITERIA_DORM_CHECKOUT,
    QUERY_CRITERIA_MAP,
)


def score_answer(answer: str, criteria: list[dict] = EVAL_CRITERIA) -> dict:
    scores = {}
    total  = 0
    for c in criteria:
        if not c["keywords"]:
            score = 2  # e.g. no_hallucination: auto full marks, manual verification
        else:
            hits  = sum(1 for kw in c["keywords"] if kw in answer)
            score = 2 if hits >= c["min_hits"] else (1 if hits > 0 else 0)
        scores[c["name"]] = score
        total += score

    return {
        "scores":  scores,
        "total":   total,
        "max":     len(criteria) * 2,
        "missing": [k for k, v in scores.items() if v < 2],
    }


def print_score_report(answer: str, criteria: list[dict] = EVAL_CRITERIA) -> None:
    result = score_answer(answer, criteria)
    print(f"\n{'='*50}")
    print(f"總分：{result['total']}/{result['max']}")
    print(f"{'='*50}")
    for name, score in result["scores"].items():
        status = "✅" if score == 2 else ("⚠️" if score == 1 else "❌")
        print(f"  {status} {name}: {score}/2")
    if result["missing"]:
        print(f"\n缺少：{result['missing']}")


if __name__ == "__main__":
    print("### 休學 — 完整答案 ###")
    complete_leave = """
    步驟一：向系所辦公室提出申請
    第一步：確認申請時間...
    行政大樓3樓 出納組
    行政大樓5樓 住宿組（住宿生）
    國際學生請至8樓國際合作處
    退費標準：全額退費 / 2/3 / 1/3
    電話分機：62123、63279、62222
    表單：QP-T01-03-02
    組長批示後送教務長核准
    王揚忠 劉吉軒
    三個工作天後可至教務處領取或郵寄
    身心健康中心 8237-7419
    """
    print_score_report(complete_leave)

    print("\n### 休學 — 刻意缺漏答案（只留規定文字，無步驟/蓋章鏈/表單/聯絡資訊）###")
    deficient_leave = """
    休學須於期末考試前辦理，逾期不予受理。休學最長二學年。
    """
    print_score_report(deficient_leave)

    print("\n### 復學 — 完整答案 ###")
    complete_resumption = """
    復學分兩種情況：
    一、期滿復學：休學或保留學籍期滿即應復學，只需依規定期限完成註冊繳費，不需另外送件申請。
    二、提早復學：如欲於期滿前提前復學，須填具提早復學申請書（QP-T01-03-04），
    依序至系所會辦、生僑組（僅男生及僑生需辦理，行政大樓3樓）、
    國際合作事務處（僅國際學生需辦理）用印後，送教務處註冊組（行政大樓4樓），
    經註冊組組長王揚忠核准即完成復學手續，不需教務長核准。
    """
    print_score_report(complete_resumption, EVAL_CRITERIA_RESUMPTION)

    print("\n### 復學 — 刻意缺漏答案（只有期滿復學，漏掉提早復學整段+表單+蓋章鏈+聯絡人）###")
    deficient_resumption = """
    休學期滿即應復學，並依規定期限辦妥註冊。
    """
    print_score_report(deficient_resumption, EVAL_CRITERIA_RESUMPTION)

    print("\n### 轉系所 — 完整答案 ###")
    complete_dept_transfer = """
    碩士班轉系所需經以下單位同意：
    一、原系所主管審核意見（同意轉出）
    二、擬轉入系所主管審核意見（同意轉入）
    三、教務處審核：註冊組承辦人 → 註冊組組長 → 教務長，三層皆需核准
    申請期間為上學期12月1日至12月31日，或下學期6月1日至6月30日，以一次為限。
    """
    print_score_report(complete_dept_transfer, EVAL_CRITERIA_DEPT_TRANSFER)

    print("\n### 退宿 — 完整答案 ###")
    complete_dorm_checkout = """
    退宿分兩種情況：
    一、學期前退宿：尚未進住或欲取消下學期續住，填寫退宿申請表（QP-M03-01-04）即可，不涉及保證金退還。
    二、離宿暨退還保證金：學期中/末搬離宿舍，先持『離宿暨退還保證金申請表』（QP-M03-01-05）
    至宿舍服務台辦理寢室檢查簽章，三天內持該表及宿費繳費收據至住宿組辦理退宿費及住宿保證金退還。
    僑生及外籍生若已出國、帳戶結清無法領取，需另填委託書將保證金匯入代領人帳戶。
    """
    print_score_report(complete_dorm_checkout, EVAL_CRITERIA_DORM_CHECKOUT)
