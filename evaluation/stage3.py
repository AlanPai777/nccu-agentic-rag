"""
evaluation/stage3.py

評測階段 3（plan/phase_k_evaluation_design.md 第 4 節）：由 Claude Code 判斷的部分，以及把判斷合併成分數。
本檔不呼叫任何 LLM；判斷由 Claude Code 讀 trace_input.json / judge_input.json 後寫出 trace.json / judge.json。

三個子命令（在專案根目錄執行）：

  python evaluation/stage3.py prepare <gold.json> <run_dir>
      由 <run_dir>/prediction.json 產生
        trace_input.json  回推用的輸入：答案正文 + 答案模型實際看到的證據項目。**不含 gold**，
                          判斷者回推時看不到標準答案。
        judge_input.json  Keypoint 判斷用的輸入：答案正文 + keypoint 文字 + gold 的 content
                          （不含 references，也不含規則版 Accuracy 的結果）。

  python evaluation/stage3.py check <run_dir>
      驗證 trace.json：每個主張的 answer_span 必須是答案正文的子字串，每段證據 quote 必須是該證據項目的
      子字串（空白正規化後）；主張的片段若被另一個主張包含，不重複計入（以較長的為準）。結果寫進
      trace.checked.json，不改動判斷者寫的 trace.json。

  python evaluation/stage3.py score <gold.json> <run_dir>
      讀 scores.stage2.json、trace.checked.json、judge.json，算出階段 3 的分數並合併成 scores.json。

命名：K = gold 的 keypoint，c = 答案的主張（claim），E = 證據項目（evidence item）。

定義（2026-11-11 與使用者確認）：
  Keypoint        Completeness / Hallucination / Irrelevance = Relevant / Wrong / Irrelevant 的 keypoint ÷ keypoint 總數
  事實為單位      P = Relevant ÷ (Relevant + Wrong)   R = Relevant ÷ keypoint 總數   F1 = 調和平均
  答案為單位      P = 正確陳述某個 keypoint 的主張 ÷ 全部主張   R = Relevant ÷ keypoint 總數   F1
                  （額外但正確的資訊在這一組會讓 P 下降，這組量的是答案聚焦程度，不是對錯）
  有依據的主張比例  有證據支持的主張 ÷ 全部主張（單獨一個數，沒有 R 與 F1；唯一管 gold 沒列的敘述）
"""
import argparse
import html
import json
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from score_programmatic import _NODE_PROMPT_PREFIXES, norm  # noqa: E402
from run_system import split_answer  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent / "registry"))
ROOT = HERE.parent
_MARKER_RE = re.compile(r"\[live:src ([^\]]*?) url=([^\]]+)\]")

OUTPUT_FORMAT = {
    "trace.json": {
        "claims": [{
            "id": "c1",
            "answer_span": "答案正文裡的一段逐字原文（這個主張對應的那一小段）",
            "status": "supported | unsupported",
            "evidence": [{"item": "E1", "quote": "該證據項目裡的一段逐字原文"},
                     {"item": "E2", "quote": "（網址主張才用）該項目 sources 裡的一個完整網址", "from": "sources"}],
            "why": "一句話說明",
        }],
        "judge": {"model": "", "prompt_version": "", "note": ""},
        "rules": [
            "把答案拆成原子主張：一個主張只講一件事（總機與分機是兩件事、傳真是另一件）。",
            "引言、標題、「如下」這類沒有事實內容的字句不要列成主張。",
            "answer_span 必須逐字取自 answer_text；quote 必須逐字取自該證據項目的 text（網址主張例外，見最後一條）；程式會驗證，找不到會被退回。",
            "status=supported 要附至少一段 evidence；找不到依據就寫 unsupported，evidence 留空陣列。",
            "判斷『有沒有依據』只看 evidence_items 裡的文字，不用你自己知道的事。",
            "把人與職稱、分機配成一對的主張，要證據把「同一個人」配「同樣的職稱與分機」才算 supported；姓名、職稱、分機任一項與證據不同（包含分機是證據裡另一個人的），就是 unsupported。",
            "一個人的姓名、職稱、分機寫成同一個主張，不要把分機拆出去（拆出去的分機會失去它屬於誰的資訊）。",
            "只出現在網址或連結位址裡的字，不算該單位職掌等內容的證據。",
            "各主張的 answer_span 不得互相重疊（一個字最多屬於一個主張）；不要同時列出整句與其中一部分。",
            "答案裡的網址主張（網址本身就是要說的內容，例如「下載連結：https://…」）可以引用證據項目的 sources：evidence 寫 {\"item\": \"E2\", \"quote\": \"<sources 裡的一個完整網址，逐字>\", \"from\": \"sources\"}。quote 必須等於 sources 裡的一個完整網址（不是網址的一部分），程式會驗證；這個網址對不對得上答案說的東西（例如是不是休學申請書的連結），要看該網址在 sources 裡的 label；網址路徑裡的字仍然不算其他主張的證據（規則 8）；網址不在 sources 裡就是 unsupported。",
        ],
    },
    "judge.json": {
        "keypoints": [{
            "id": "K1",
            "verdict": "relevant | irrelevant | wrong | not_applicable",
            "claims": ["c1"],
            "reason": "一句話說明",
        }],
        "judge": {"model": "", "prompt_version": "", "note": ""},
        "rules": [
            "relevant：答案裡有與這個 keypoint 相關且一致的陳述（不必每個細節都一樣，最重要的資訊一致即可）。",
            "irrelevant：答案沒有提到，或只說資訊不足。",
            "wrong：答案對這個 keypoint 給了具體但不同的內容。",
            "not_applicable：只用在有適用條件的 keypoint（text 寫「答案若…」）。答案沒有滿足條件（例如根本沒列承辦人）時判 not_applicable，不計入分母；滿足條件才判 relevant 或 wrong。",
            "claims 列出 trace.json 裡直接陳述這個 keypoint 的主張編號；沒提到就留空陣列。同一個主張可以同時連到多個 keypoint。",
            "每個 keypoint 都要有一筆。",
        ],
    },
}


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# --- prepare ------------------------------------------------------------------
# 系統自己加在聯絡人清單裡的來源行（format_context 產生）：整行只有「來源：」或「補充來源（…）：」加一個網址。
# 與答案的「來源：」行同樣不評分（不做引用來源指標），所以從證據裡也剝掉；否則網址路徑裡的字（例如「退費」）
# 會讓一個關於職掌的主張被誤判為有依據。窄規則：整行都是網址才剝，不碰網頁內文裡的連結。
# 只剝給判斷者看的 trace_input.json；prediction.json 的 context 原樣保留。
_SRC_LINE_RE = re.compile(r"^[ \t]*(?:補充)?來源(?:（[^）]*）)?[：:][ \t]*https?://\S+[ \t]*$", re.M)


_SRC_LINE_PARTS_RE = re.compile(r"^[ \t]*((?:補充)?來源(?:（[^）]*）)?)[：:][ \t]*(https?://\S+)[ \t]*$")


def _norm_url(u: str) -> str:
    """網址比對用的正規化：解開網址編碼與 &amp;、小寫的協定與主機、去掉 # 後面與結尾的斜線。路徑與查詢字串照原樣（大小寫有意義）。"""
    u = urllib.parse.unquote(html.unescape((u or "").strip())).split("#", 1)[0].rstrip("/")
    p = urllib.parse.urlsplit(u)
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), p.query, ""))


def _label_from_line(line: str) -> str:
    """標記行前一行的名稱：get_form 取得表單 <標題> → 標題；get_page 取得 N 字，標題: <標題>，subdomain: … → 標題；其他原樣。"""
    line = line.strip()
    m = re.match(r"get_form 取得表單\s*(.*)$", line)
    if m:
        return re.sub(r"（官網顯示此表單已停用[^）]*）$", "", m.group(1)).strip()
    m = re.search(r"標題:\s*(.*?)(?:，subdomain:.*)?$", line)
    if line.startswith("get_page") and m:
        return m.group(1).strip()
    return line[:120]


def _sources_of(text: str) -> list[dict]:
    """這個證據項目裡系統看到的網址（標記行的 url=，以及被剝掉的純網址來源行），各附名稱（label）。
    網址主張靠它判斷「系統有沒有看過這個網址」；label 讓判斷者確認這個網址對得上答案說的東西。"""
    out, seen = [], set()

    def add(url, label):
        key = _norm_url(url)
        if key and key not in seen:
            seen.add(key)
            out.append({"url": url, "label": label})

    for m in _MARKER_RE.finditer(text):
        before = text[:m.start()].rstrip().splitlines()
        add(m.group(2), _label_from_line(before[-1]) if before else "")
    for ln in text.splitlines():
        m = _SRC_LINE_PARTS_RE.match(ln)
        if m:
            add(m.group(2), m.group(1))
    return out


def build_evidence(context: list[dict]) -> tuple[list[dict], list[str]]:
    """答案模型實際看到的內容：工具輸出、聯絡人清單（contact_list）、節點注入的資料（表單全文等）。
    排除 contact_page（人員頁原文，答案模型沒看過，只用於 Context 層）與節點給 LLM 的指示文字；
    剝掉 [live:src …] 標記行與純網址的來源行（網址與前一行的名稱另存在 sources，網址主張用）。回傳 (證據項目, 被剝掉的來源行)。"""
    items, removed = [], []
    for c in context:
        if c.get("kind") == "contact_page":
            continue
        if c["role"] == "HumanMessage" and c["text"].startswith(_NODE_PROMPT_PREFIXES):
            continue
        m = _MARKER_RE.search(c["text"])
        sources = _sources_of(c["text"])
        text = _MARKER_RE.sub("", c["text"])
        removed += [ln.strip() for ln in text.splitlines() if _SRC_LINE_RE.match(ln)]
        text = _SRC_LINE_RE.sub("", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        items.append({
            "id": f"E{len(items) + 1}",
            "kind": c.get("kind") or c["role"],
            "tool": c.get("tool"),
            "source_url": m.group(2) if m else None,     # 第一個標記的網址（舊欄位）；全部的網址看 sources
            "sources": sources,
            "text": text,
        })
    return items, removed


def cmd_prepare(gold_path: Path, run_dir: Path) -> None:
    gold = _read(gold_path)
    pred = _read(run_dir / "prediction.json")
    body, stripped = split_answer(pred["answer_raw"])      # 舊的 prediction 也能用：從 answer_raw 重算
    answer_text = body.replace("**", "")
    evidence, removed_src = build_evidence(pred["context"])
    av = gold.get("allowed_values") or {}
    notes = {}
    if av.get("extension"):
        notes["允許的出納組分機"] = [e["value"] for e in av["extension"]]
    if av.get("disallowed"):
        notes["不屬於這個單位的號碼（答案寫了就是錯）"] = [f"{d['value']}：{d['reason']}" for d in av["disallowed"]]

    used = sorted({k["registry"]["office"] for k in gold["keypoints"] if k.get("registry", {}).get("office")})
    if used:   # 引用登記表的單位：把允許的人員、代表線、樓層列給評審看（配對與樓層由程式檢查，評審只作參考）
        import registry_lib
        reg = registry_lib.load()
        notes["登記表允許的單位資料（姓名接受全名或姓氏＋職稱，姓氏＋小姐／先生也算）"] = {o: registry_lib.allowed_for_judge(reg, o) for o in used}

    _write(run_dir / "trace_input.json", {
        "query_id": gold["query_id"], "run_id": pred["run_id"],
        "task": "回推：把 answer_text 拆成原子主張，為每個主張在 evidence_items 找出支持它的逐字原文；找不到就標 unsupported。",
        "answer_text": answer_text,
        "stripped_not_scored": {"rationale": stripped["rationale"], "sources": stripped["sources"], "disclosure": stripped["disclosure"],
                                "evidence_source_lines": removed_src},
        "evidence_items": evidence,
        "output_file": "trace.json",
        "output_format": OUTPUT_FORMAT["trace.json"],
    })
    if av.get("extension_by_person"):
        notes["承辦人與分機的正確配對（人員頁）"] = [f"{p['name']}（{p['title']}）：{p['extension']}" for p in av["extension_by_person"]]
    _write(run_dir / "judge_input.json", {
        "query_id": gold["query_id"], "run_id": pred["run_id"], "query": pred["query"],
        "task": "對每個 keypoint 判斷答案：relevant / irrelevant / wrong，並指出直接陳述它的主張編號（見 trace.json）。",
        "answer_text": answer_text,
        "gold_content": gold["content"],
        "keypoints": [{"id": k["id"], "text": k["text"], **({"applies_if": k["applies_if"]} if k.get("applies_if") else {})}
                      for k in gold["keypoints"]],
        "notes": notes,
        "output_file": "judge.json",
        "output_format": OUTPUT_FORMAT["judge.json"],
    })
    print(f"已寫入 {run_dir}/trace_input.json（答案 {len(answer_text)} 字、證據項目 {len(evidence)} 個）與 judge_input.json（{len(gold['keypoints'])} 個 keypoint）")
    print(f"剝掉未評分的：選擇原因 {len(stripped['rationale'])} 句；來源行 {'有' if stripped['sources'] else '無'}；資料狀態 {'有' if stripped['disclosure'] else '無'}；證據裡的來源行 {len(removed_src)} 行")


# --- check --------------------------------------------------------------------
def _locate(haystack: str, needle: str):
    """needle 在 haystack 中的位置（空白正規化後找，位置回報原文位置；找不到回 None）。"""
    i = haystack.find(needle)
    if i != -1:
        return i, i + len(needle)
    n = norm(needle)
    if not n or n not in norm(haystack):
        return None
    return -1, -1     # 在正規化後找得到，但原文位置無法精確回報


def _occurrences(text: str, needle: str) -> list[tuple[int, int]]:
    out, i = [], text.find(needle) if needle else -1
    while i != -1:
        out.append((i, i + len(needle)))
        i = text.find(needle, i + 1)
    return out


def cmd_check(run_dir: Path) -> dict:
    out = check_trace(_read(run_dir / "trace_input.json"), _read(run_dir / "trace.json"))
    _write(run_dir / "trace.checked.json", out)
    claims, warnings = out["claims"], out["warnings"]
    ok = sum(1 for c in claims if c["span_verified"])
    dropped = [c["id"] for c in claims if not c["counted"]]
    print(f"主張 {len(claims)} 個；answer_span 通過 {ok} 個" + (f"；因被包含不計入 {len(dropped)} 個（{', '.join(dropped)}）" if dropped else "") + f"；證據 quote 通過 {sum(e['verified'] for c in claims for e in c['evidence'])}/{sum(len(c['evidence']) for c in claims)}")
    for w in warnings:
        print("  警告：", w)
    return out


def check_trace(ti: dict, tr: dict) -> dict:
    """純函式：驗證 trace（不讀寫檔案）。回傳 {claims, judge, warnings}，claims 帶 span_verified、counted、span_pos 等欄位。"""
    items = {e["id"]: e for e in ti["evidence_items"]}
    answer = ti["answer_text"]
    warnings, claims = [], []
    for c in tr["claims"]:
        c = dict(c)
        loc = _locate(answer, c.get("answer_span", ""))
        c["span_verified"] = loc is not None
        if loc is None:
            warnings.append(f"{c['id']}：answer_span 不在答案正文裡，這個主張不計入")
        ev = []
        for e in c.get("evidence", []):
            e = dict(e)
            it = items.get(e.get("item"))
            if e.get("from") == "sources":
                # 網址主張：quote 必須等於該項目 sources 裡的一個完整網址（正規化後精確比對，不是子字串）
                target = _norm_url(e.get("quote", ""))
                hit = next((s_ for s_ in (it or {}).get("sources", []) if target and _norm_url(s_["url"]) == target), None)
                e["verified"], e["quote_in"] = hit is not None, "sources"
                if hit:
                    e["label"] = hit.get("label", "")
                else:
                    warnings.append(f"{c['id']}：證據 {e.get('item')} 的 quote 不等於該項目 sources 裡任何一個完整網址，不算有效證據")
            elif e.get("from") not in (None, ""):
                e["verified"] = False
                warnings.append(f"{c['id']}：證據 {e.get('item')} 的 from 只能是 sources，這筆不算有效證據")
            else:
                pos = _locate(it["text"], e.get("quote", "")) if it else None
                e["verified"] = pos is not None
                if pos and pos[0] >= 0:
                    e["start"], e["end"] = pos
                if pos is None:
                    warnings.append(f"{c['id']}：證據 {e.get('item')} 的 quote 不是該項目的原文，不算有效證據")
            ev.append(e)
        c["evidence"] = ev
        valid_evidence = [e for e in ev if e["verified"]]
        status = c.get("status")
        if status == "supported" and not valid_evidence:
            c["status_checked"] = "unsupported"
            warnings.append(f"{c['id']}：標為 supported 但沒有任何通過驗證的證據，降為 unsupported")
        else:
            c["status_checked"] = status
        claims.append(c)
    # 主張的片段不得互相重疊：被另一個主張包含的短主張會被算兩次（整句與其中一部分各算一個），
    # 讓「有依據的主張比例」偏高。被包含的不計入，以較長的為準；只部分重疊的只警告。
    assigned: list[tuple[str, tuple[int, int]]] = []
    for c in claims:
        c["counted"] = True
        if not c["span_verified"]:
            continue
        occ = _occurrences(answer, c.get("answer_span", ""))
        if not occ:
            c["span_pos"] = None          # 只有正規化後才找得到，無法判斷位置
            continue
        free = [o for o in occ if all(o[1] <= a[0] or o[0] >= a[1] for _, a in assigned)]
        pos = free[0] if free else occ[0]  # 同一段文字出現多次時，取第一個還沒被別的主張用掉的位置
        c["span_pos"] = list(pos)
        c["overlaps_with"] = [cid for cid, a in assigned if not (pos[1] <= a[0] or pos[0] >= a[1])]
        assigned.append((c["id"], pos))
    by_id = {c["id"]: c for c in claims}
    for c in claims:
        for oid in c.get("overlaps_with", []):
            o = by_id[oid]
            (cs, ce), (os_, oe) = c["span_pos"], o["span_pos"]
            if cs >= os_ and ce <= oe:
                c["counted"], c["contained_in"] = False, oid
                warnings.append(f"{c['id']} 的片段被 {oid} 包含，不重複計入（以較長的 {oid} 為準）")
            elif os_ >= cs and oe <= ce:
                o["counted"], o["contained_in"] = False, c["id"]
                warnings.append(f"{oid} 的片段被 {c['id']} 包含，不重複計入（以較長的 {c['id']} 為準）")
            else:
                warnings.append(f"{c['id']} 與 {oid} 的片段部分重疊，兩者都計入")
    return {"claims": claims, "judge": tr.get("judge"), "warnings": warnings}


# --- score --------------------------------------------------------------------
def _f1(p, r):
    return None if p is None or r is None or (p + r) == 0 else round(2 * p * r / (p + r), 4)


def _r(x):
    return None if x is None else round(x, 4)


def cmd_score(gold_path: Path, run_dir: Path) -> dict:
    gold = _read(gold_path)
    st2 = _read(run_dir / "scores.stage2.json")
    tr = cmd_check(run_dir)
    jd = _read(run_dir / "judge.json")
    warnings = list(tr["warnings"])

    claims = [c for c in tr["claims"] if c["span_verified"] and c.get("counted", True)]
    by_claim = {c["id"]: c for c in claims}
    alias = {c["id"]: c["contained_in"] for c in tr["claims"] if c.get("contained_in")}   # 被包含的主張改算它的容器
    verdicts = {k["id"]: k for k in jd["keypoints"]}
    K_all = len(gold["keypoints"])
    for k in gold["keypoints"]:
        if k["id"] not in verdicts:
            warnings.append(f"judge.json 缺少 {k['id']}，視為 irrelevant")
            verdicts[k["id"]] = {"id": k["id"], "verdict": "irrelevant", "claims": [], "reason": "（缺漏）"}
    for kid, v in verdicts.items():
        if v["verdict"] not in ("relevant", "irrelevant", "wrong", "not_applicable"):
            warnings.append(f"{kid}：verdict {v['verdict']!r} 不合法，視為 irrelevant")
            v["verdict"] = "irrelevant"
    rel = sum(v["verdict"] == "relevant" for v in verdicts.values())
    wrong = sum(v["verdict"] == "wrong" for v in verdicts.values())
    na = sum(v["verdict"] == "not_applicable" for v in verdicts.values())
    K = K_all - na                       # 不適用的條件式 keypoint 不計入分母
    irr = K - rel - wrong

    # 事實為單位
    p_fact = rel / (rel + wrong) if (rel + wrong) else None
    r_fact = rel / K if K else None

    # 答案為單位：正確陳述某個 keypoint 的主張
    linked_ok = set()
    for v in verdicts.values():
        if v["verdict"] == "relevant":
            linked_ok |= {alias.get(cid, cid) for cid in v.get("claims", []) if alias.get(cid, cid) in by_claim}
    C = len(claims)
    p_claim = len(linked_ok) / C if C else None

    # 有依據的主張比例
    supported = [c for c in claims if c["status_checked"] == "supported"]
    unsupported = [c["id"] for c in claims if c["status_checked"] != "supported"]
    support_rate = len(supported) / C if C else None

    # 答對但沒有依據的 keypoint
    ungrounded = [kid for kid, v in verdicts.items() if v["verdict"] == "relevant"
                  and not any(by_claim.get(alias.get(cid, cid), {}).get("status_checked") == "supported" for cid in v.get("claims", []))]

    # 規則版 Accuracy 與 Claude 判斷不一致的 keypoint
    rule = {r["id"]: r for r in st2["keypoints"]["accuracy_rule"]}
    disagreements = []
    for kid, v in verdicts.items():
        rv = rule.get(kid, {}).get("verdict")
        if rv in (None, "needs_llm"):
            continue
        ok = (rv == "hit" and v["verdict"] == "relevant") or (rv == "wrong" and v["verdict"] == "wrong") \
            or (rv == "miss" and v["verdict"] in ("irrelevant", "wrong")) \
            or (rv == "not_applicable" and v["verdict"] == "not_applicable")
        if not ok:
            disagreements.append({"keypoint": kid, "rule": rv, "claude": v["verdict"], "claude_reason": v.get("reason", ""),
                                  "rule_detail": {k: rule[kid].get(k) for k in ("matched_expressions", "wrong") if rule[kid].get(k)}})

    funnel = []
    ctx = {f["id"]: f for f in st2["keypoints"]["funnel_stage2"]}
    for k in gold["keypoints"]:
        v = verdicts[k["id"]]
        if v["verdict"] == "not_applicable":
            funnel.append({"id": k["id"], "verdict": "not_applicable", "in_context": None, "stated_correctly": None, "grounded": None})
            continue
        funnel.append({
            "id": k["id"],
            "in_context": ctx.get(k["id"], {}).get("in_context"),
            "stated_correctly": v["verdict"] == "relevant",
            "grounded": k["id"] not in ungrounded and v["verdict"] == "relevant",
            "verdict": v["verdict"],
        })

    scores = {
        "query_id": st2["query_id"], "run_id": st2["run_id"], "system_version": st2.get("system_version"),
        "gold_data_as_of": st2.get("gold_data_as_of"),
        "judges": {"trace": (tr.get("judge") or {}), "keypoint": jd.get("judge")},
        "rouge_l": st2["rouge_l"],
        "accuracy_rule": st2["accuracy"],
        "context": st2["context"],
        "keypoint": {"relevant": rel, "wrong": wrong, "irrelevant": irr, "total": K, "not_applicable": na,
                     "completeness": _r(rel / K) if K else None, "hallucination": _r(wrong / K) if K else None,
                     "irrelevance": _r(irr / K) if K else None},
        "fact_unit": {"precision": _r(p_fact), "recall": _r(r_fact), "f1": _f1(p_fact, r_fact),
                      "note": "P = Relevant ÷ (Relevant + Wrong)；R = Relevant ÷ keypoint 總數"},
        "claim_unit": {"claims": C, "correct_claims": len(linked_ok), "precision": _r(p_claim), "recall": _r(r_fact),
                       "f1": _f1(p_claim, r_fact),
                       "note": "P = 正確陳述某個 keypoint 的主張 ÷ 全部主張；額外但正確的資訊會讓 P 下降，量的是聚焦程度"},
        "evidence_support": {"rate": _r(support_rate), "supported": len(supported), "claims": C, "unsupported_claims": unsupported},
        "ungrounded_correct_keypoints": ungrounded,
        "funnel": funnel,
        "contact_funnel": st2["keypoints"].get("contact_funnel", []),
        "disagreements": disagreements,
        "warnings": warnings,
    }
    _write(run_dir / "scores.json", scores)

    def fmt(x):
        return "—" if x is None else f"{x:.2f}"
    print(f"\n題目：{gold['query']}   run：{st2['run_id']}")
    print(f"Keypoint            Completeness {fmt(scores['keypoint']['completeness'])}  Hallucination {fmt(scores['keypoint']['hallucination'])}  Irrelevance {fmt(scores['keypoint']['irrelevance'])}   (relevant {rel} / wrong {wrong} / irrelevant {irr}" + (f" / 不適用 {na}" if na else "") + ")")
    print(f"事實為單位 P／R／F1   {fmt(p_fact)} / {fmt(r_fact)} / {fmt(scores['fact_unit']['f1'])}")
    print(f"答案為單位 P／R／F1   {fmt(p_claim)} / {fmt(r_fact)} / {fmt(scores['claim_unit']['f1'])}   (主張 {C}，正確 {len(linked_ok)})")
    print(f"有依據的主張比例      {fmt(support_rate)}   ({len(supported)}/{C})" + (f"  沒依據：{unsupported}" if unsupported else ""))
    print(f"Accuracy（規則）      {st2['accuracy']['hit']}/{st2['accuracy']['hard_keypoints']}   ROUGE-L P／R／F {st2['rouge_l']['p']:.2f}/{st2['rouge_l']['r']:.2f}/{st2['rouge_l']['f']:.2f}")
    print(f"Context 句子 R {fmt(st2['context']['sentence']['r'])}  詞 R {fmt(st2['context']['words']['r'])}")
    if ungrounded:
        print("答對但沒依據的 keypoint：", ungrounded)
    print("規則與 Claude 不一致：", disagreements or "無")
    for w in warnings:
        print("警告：", w)
    print(f"\n已寫入 {run_dir}/scores.json")
    return scores


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("prepare"); a.add_argument("gold"); a.add_argument("run_dir")
    b = sub.add_parser("check"); b.add_argument("run_dir")
    c = sub.add_parser("score"); c.add_argument("gold"); c.add_argument("run_dir")
    args = ap.parse_args()
    if args.cmd == "prepare":
        cmd_prepare(Path(args.gold).resolve(), Path(args.run_dir).resolve())
    elif args.cmd == "check":
        cmd_check(Path(args.run_dir).resolve())
    else:
        cmd_score(Path(args.gold).resolve(), Path(args.run_dir).resolve())


if __name__ == "__main__":
    main()
