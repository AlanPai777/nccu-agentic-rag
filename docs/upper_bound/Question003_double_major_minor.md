# Question 003 — 碩士班雙主修輔系申請需要經過哪些單位審核

**Date:** 2026-09-18
**Pipeline:** `agentic_rag.py`（Gemma4:31b-cloud via Ollama Cloud）
**架構模式：** 跨處室 — 三段連續審核（所屬學系 → 申請學系 → 教務處註冊組，比並行雙處室多一段，教務處那段本身還有兩層）
**Criteria:** `rag/eval_criteria/double_major_minor.py`（`EVAL_CRITERIA_DOUBLE_MAJOR_MINOR`，6 項 × 2 = 12 分）

## 方法論

Sonnet 直接讀 `output/aca/extracted_supplementary.jsonl` 裡 `QP-T01-03-08`（碩、博士班學生修讀雙主修輔系申請表）表單原文查證，非查記憶。

## 表單原文關鍵段落

```
簽核流程：
  所屬學系(所)：是否同意所屬學生申請修讀雙主修/輔系 [承辦人 + 單位主管]
  申請學系(所)：准予/不准修讀，適用規定 XX學年度必修/輔系科目表 [承辦人 + 單位主管]
  教務處註冊組：審查基本資格及維護資料 [承辦人 + 組長]

本人已知悉：
  2. 本次申請之雙主修/輔系如經核定修讀，視同自願放棄原有之雙主修或輔系資格，且不得再申請回復。

申請資格：自註冊在學第二學期起至第四學期止。
```

## Gold Standard 答案

碩士班申請雙主修/輔系需經三個單位：(1) 所屬學系(原系所)同意、(2) 申請學系(目標系所)准予修讀、(3) 教務處註冊組承辦人+組長雙層審查基本資格。申請時窗為註冊在學第二至第四學期，一旦核定即視同自願放棄原有雙主修/輔系資格且不得再申請回復。

## 系統實際輸出

**總分：9/12（第一次）→ 10/12（修正 criteria 後離線重評）**

檢索路徑：`search_texts('碩士雙主修輔系申請審核')` 命中 `aca` 子網域的**公告摘要頁**（`5545-本校碩博士班學生申請修讀校內雙主修-輔系公告`，非表單 PDF 本身），`get_page_tool` 抓取後該 ToolMessage 出現「[偵測到表單編號: QP-T01-03-08]」標記，3 輪內收斂。

人工核對答案內容：三段審核單位、註冊組承辦/組長、申請時窗全部正確且有真實聯絡人（王揚忠·組長 分機63273），無幻覺。扣分兩項分開處理：

- `registrar_review`（1/2 → criteria 修正後 2/2）：答案用「行政承辦窗口」而非字面「承辦人」，**criteria 用詞太窄**，加入「承辦」後修正。同 Question002 的用詞不符是同一類問題。
- `no_reapply_rule`（0/2，維持原樣，**但診斷已修正**）：答案完全沒提到「視同自願放棄」這條規則。

  **初步診斷（已修正）**：一開始以為是「agent 沒有真的抓表單本文」（純檢索缺口）。但查 code 發現 `_after_tools`（`rag/agentic/nodes/loop.py:178-181`）偵測到 `[偵測到表單編號]` 標記時一定會路由到 `resource_node`，而這次 trace 確實出現這個標記；`resource_node`（`rag/agentic/nodes/resource.py:74-84`）會把抓到的表單全文包成 `HumanMessage` 塞進對話——但 CLI 的 `_render_messages()`（`rag/agentic/logic/rewrite.py:79-91`）只印 `AIMessage`/`ToolMessage`，**完全跳過 `HumanMessage`**，所以 trace 看不出表單本文有沒有被抓到。這次「3輪」（多於單純 2 次工具呼叫預期的輪數）符合「`resource_node` 抓完表單後多繞一輪 `rewrite_node`」的行為模式，間接支持表單其實有被抓到。

  **修正後診斷**：表單全文（含「視同自願放棄」那句）很可能已經進了 synthesis 的 context，只是 synthesis 沒有把這條「注意事項」寫進最終答案——是 **synthesis 階段遺漏**，不是檢索沒抓到。這跟原本歸類的「找到候選就停、沒查證更權威來源」是不同的失敗模式，修法也不同（前者要修 synthesis prompt 對「注意事項/限制規則」類資訊的涵蓋要求，後者要修檢索邏輯本身）。

## 結論

**Criteria 部分修正（`registrar_review` 用詞放寬），`no_reapply_rule` 維持原樣，但失敗模式歸類已修正為「synthesis 遺漏」而非「檢索缺口」。** 這題額外浮現一個獨立於本題 criteria 的系統性問題：**CLI trace 對 `resource_node`/`contact_node` 抓到的內容不可見**（`_render_messages()` 跳過 `HumanMessage`），導致光看預設輸出無法分辨「檢索沒抓到」跟「抓到了但 synthesis 沒寫進答案」——這兩種失敗的修法完全不同，卻長得一樣。這個觀測缺口已記錄在 `README.md`「獨立發現」，值得未來考慮讓 `--stream` 或預設 trace 也印出 `HumanMessage` 內容（至少印出開頭的標記行，不用印全文）。
