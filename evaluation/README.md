# evaluation/

標準答案（gold）與評測程式。每個題目一個子資料夾：`leave_of_absence/`（如何辦理休學，事實表格式）、`cashier_contact/`（出納組電話幾號，新格式 `gold.json`，已跑通整條管線）。評測的設計、定義與決策見 `plan/phase_k_evaluation_design.md`（第 13 節是階段 3 的定義）。

## 原則

1. **抽取，不是生成**：每個事實必須附一段**逐字引句**，引句必須出現在來源原文中。`leave_of_absence/build_facts.py` 在寫檔前會逐條驗證（忽略空白與表格線，並做 Unicode 相容正規化），任何一條找不到就中止，不寫檔。
2. **資料日期固定**：用 `output/` 現有快照（校務頁面 2026-08-19、處室人員索引 2026-08-25），不是今天的官網。要測現場查證時，另外標註。
3. **只指定處室，不指定個人**：個人只作為候選，驗證條件是「屬於該處室」。
4. **標準答案不依賴系統輸出**：事實從表單與頁面原文抽出，不是從舊 criteria 或系統答案反推。舊 criteria 只用於 `crosscheck.md` 的對照。

## `leave_of_absence/` 內容

| 檔案 | 用途 |
|---|---|
| `reference_answer.md` | 給人讀的標準答案（短版）：重點（怎麼辦、去哪裡，聯絡人跟著各站走）＋補充＋附表，不含事實編號 |
| `facts.jsonl` | 事實表（56 項）：`id`、`layer`（1 流程、2 位置/電話）、`content`、`quote`（原文引句）、`source`、`source_url`、`acceptable_expressions`、`note` |
| `candidates.jsonl` | 各站聯絡人候選（41 筆）：`station`、`tier`（source_specified 來源指定／duty_derived 依職掌／head 單位主管／other_staff 同處室但職掌不符）、`scope`、`basis`（原文依據）、`person_source`。個人只是候選，唯一要求是「人屬於那一站」 |
| `contradictions.jsonl` | 易寫錯的數字與處室，含自然語言說明與**草稿**正規式 |
| `crosscheck.md` | 與舊 criteria 的逐項對照 |
| `sources/` | 引用到的來源原文複本（23 份：表單、aca／osa／oic 頁面、人員索引條目；osa FAQ 只複製引用段落），檔頭標註來源檔案與網址 |
| `sources/forms/` | 三張表單的**原始 PDF**（QP-T01-03-02 休學/保留學籍申請書、QP-T01-02-05 委託書、QP-T01-03-04 提早復學申請書），自 `output/aca/supplementary/` 複製，與原檔逐位元相同 |
| `runs/` | 真實系統答案與判讀（`run1_*`） |
| `build_facts.py` | 產生以上檔案的腳本（可重跑） |

## run 的管理

- 每次 `run_system.py` 都建新資料夾 `runs/<run_id>/`，**不覆蓋舊的**；目前 `run_id` 是流水號 `run01`、`run02`…（`new_run_id()` 一個函式，之後要改隨機碼只改它）。
- 路徑不帶資訊。時間、模型、`system_version`、標籤都在 `prediction.json` 裡；看有哪幾次用 `python evaluation/list_runs.py evaluation/<題>`。
- 不要的 run 自己刪資料夾（像 Langfuse 自己決定刪不刪 trace）。已 commit 的，git 歷史還在；沒 commit 就刪掉就沒了。
- 刪掉最後一個之後，下一個 run 會重用那個編號，所以不要在文件或 commit 訊息裡永久引用某個編號；要引用就靠標籤。
- `cashier_contact/runs/` 裡 `run01` 是原 `20261109-234225`（改名時一併改了檔案裡的 `run_id`）；另外三個以時間命名的是更早的試跑，尚未整理。

## 已知限制

- 聯絡人的「選擇原因」是模型寫的，不在來源裡，標準答案不收，評分時如何處理另行討論。
- `contradictions.jsonl` 的正規式是草稿：已用 6 句刻意寫錯的句子確認能命中，並確認不會誤判標準答案本身的句子；**尚未用真實系統答案測試**，不要直接當評分規則。
- `acceptable_expressions` 是人工列出的常見說法，覆蓋度要等跑過真實答案才知道。
- `facts.jsonl` 的事實由人逐條讀原文挑選，不是窮舉原文每一句；沒有被選入的句子不代表不重要。
- 重跑 `build_facts.py` 需在專案根目錄、`output/` 存在的情況下執行。


---

# 評測管線與測試（2026-11-11）

下面的指令都在專案根目錄執行。出納組是目前唯一跑通整條管線的題目。

## 管線

| 階段 | 指令 | 做什麼 | 需要核准 |
|---|---|---|---|
| 0 建 gold | `python evaluation/cashier_contact/build_gold.py` | 從來源原文建 `gold.json`，每條引句逐字驗證，找不到就中止、不寫檔 | 上網查證官網前要使用者批准 |
| 1 跑系統 | `python evaluation/run_system.py evaluation/cashier_contact/gold.json --label "…"` | 跑一次 `agentic_rag`（`live=False`），存 `runs/<run_id>/prediction.json`（答案與系統讀到的內容）；`--label` 選填 | **會呼叫 ollama-cloud，要使用者指示才跑** |
| 2 程式計算 | `python evaluation/score_programmatic.py <gold> <run_dir>/prediction.json` | ROUGE-L、規則版 Accuracy、Context 的 Sentence／Words P／R／F1、漏斗前半 | 無，離線 |
| 3 準備 | `python evaluation/stage3.py prepare <gold> <run_dir>` | 產生 `trace_input.json`（答案正文＋答案模型實際看到的證據，**不含 gold**）與 `judge_input.json` | 無，離線 |
| 3 回推（隔離） | 只把 `trace_input.json` 複製到全新的空資料夾，交給新的子代理，寫出 `trace.json` | 答案拆成原子主張，為每個主張找證據；做法見 `cashier_contact/tests/README.md` | 開子代理要使用者同意 |
| 3 Keypoint 判斷 | 讀 `judge_input.json` 與 `trace.json`，寫 `judge.json` | 每個 keypoint 判 relevant／irrelevant／wrong／not_applicable，並連到直接陳述它的主張 | 由 Claude Code 做，不呼叫 ollama |
| 3 驗證 | `python evaluation/stage3.py check <run_dir>` | `answer_span` 與每段證據 `quote` 必須是原文的子字串；被包含的短主張不重複計入 | 無，離線 |
| 3 算分 | `python evaluation/stage3.py score <gold> <run_dir>` | 合併成 `scores.json` | 無，離線 |

跑系統與任何 `nccu.edu.tw` 請求前，先看 `CLAUDE.md` 的 Live fetch 一節；跑測試與評測一律設 `LIVE_BROWSER=off`（腳本已經在 import 前設好）。

## 測試

```bash
python -m unittest discover -s evaluation/tests -v     # 40 個測試，約 35 秒，離線，不呼叫任何 LLM（2026-11-11 驗證）
python evaluation/compare_tests.py evaluation/cashier_contact/tests/tampered_v1    # 隔離回推記錄與鑰匙的比對
```

| 測試檔 | 檢查什麼 |
|---|---|
| `test_split_answer.py` | 答案剝除：資料狀態、來源行、「——選擇原因：…」；正文裡的「來源」二字、非網址的來源行不會被誤剝 |
| `test_rule_accuracy.py` | 規則版 Accuracy 在 7 種手寫答案上的判定：K1 總機、K2 任一允許分機、K3 條件式（配對）；未知分機、禁止值、不適用 |
| `test_stage3_prepare.py` | 證據的篩選與剝除（contact_page、節點指示、標記行、純網址的來源行）；`prepare` 的輸入不含 gold |
| `test_stage3_check.py` | 主張驗證：片段與引文要是原文、編造引文降級、重疊與包含、同一段文字出現兩次不算重疊 |
| `test_stage3_score.py` | **定義凍結檢查**：乾淨、改壞、沒列承辦人三個案例的所有分數；不一致與缺漏的判斷 |
| `test_compare_tests.py` | 比對腳本：記錄的 run1 抓到 6/6、對照 3/3；漏抓、誤判對照、ambiguous、未涵蓋、結束碼 |
| `test_gold_files.py` | 通用：掃 `evaluation/*/gold.json`，引文都在來源原文、編號不重複、允許集合一致 |

`test_stage3_score.py` 的數字是與使用者確認過的指標定義。這個測試失敗，代表有人改了指標的算法：那是定義變更，要註明版本，舊分數不能與新分數直接比較。

固定資料在 `evaluation/tests/fixtures/`（出納組乾淨 run 的 prediction、隔離回推、判斷，以及改壞答案的判斷）；改壞答案本身與隔離回推記錄在 `cashier_contact/tests/tampered_v1/`，測試直接讀它，不複製。

## 檔案

| 檔案 | 用途 |
|---|---|
| `run_system.py` | 階段 1：跑系統並存 prediction；`split_answer` 也在這裡 |
| `score_programmatic.py` | 階段 2 |
| `stage3.py` | 階段 3：`prepare`、`check`、`score`；`OUTPUT_FORMAT` 是給判斷者的格式與規則 |
| `compare_tests.py` | 隔離回推結果與鑰匙的比對 |
| `list_runs.py` | 列出一題所有 run 的標籤、時間、模型、版本、分數（唯讀、離線） |
| `leave_form_download/` | 休學申請表下載題（第一題資源類）：`gold.json`（K1 表單編號、K2 moltke 網址）、`build_gold.py`、`sources/`（含 moltke 連結回 302 的查證記錄）、`tests/pipeline_setup/`（4 份假設答案的流程測試，`report.md`，不是評測結果） |
| `course_limit/` | 選課上限題：`gold.json`、`build_gold.py`、`sources/`（快照複本、現場 PDF／HTML 與 `live_check.md` 查證記錄）。第一題非聯絡人題，7 個 keypoint（一個事實一個；數字型 `hard`、文字敘述型 `semantic`）；`tests/pipeline_setup/` 是用假設答案讓管線跑一次的流程測試（`report.md`，不是評測結果） |
| `registry/` | 單位登記表（各題共用、只維護一份）：`registry.json`（註冊組、生僑組、國合處的人員、樓層、代表線，以及表單；每個名字同時記快照與現場兩種寫法，每條都附逐字引句與來源）、`build_registry.py`（建置並逐字驗證）、`registry_lib.py`（比對：姓名＋分機、樓層、表單連結；gold 用 `"registry": {...}` 欄位引用）、`f19_gap_report.py`（F19 差距報告：新舊頁面的狀態、系統原本的解析器能讀出幾個人；只讀、離線）、`fetch_live_page.py`（人員頁一律用動態抓取，預設只列網址，加 `--run` 才送）、`sources/`（快照複本與現場原始頁面、`live_check.md` 查證記錄） |
| `resumption/` | 如何辦理復學（第一題跨處室程序題）：`gold.json`（24 個 keypoint，蓋章一個單位一個 keypoint；人員、樓層、表單連結 8 個引用登記表）、`build_gold.py`、`sources/`、`tests/pipeline_setup/`（5 份假設答案的流程測試，`report.md`，不是評測結果） |
| `leave_of_absence/` | 如何辦理休學（第二題跨處室程序題）：`gold.json`（60 個 keypoint，14 個引用登記表，14 個選擇性）、`build_gold.py`、`sources/`（含總務處 8 頁新人員頁）、`tests/pipeline_setup/`（5 份假設答案的流程測試，`report.md`，不是評測結果）。舊的 `old_leave_of_absence/` 只當參考，不是評測的一部分 |
| `cashier_contact/` | 出納組：`gold.json`、`build_gold.py`、`sources/`（來源原文複本與官網查證記錄）、`runs/`（每次 run）、`tests/`（隔離回推材料） |
| `tests/` | 評測程式的單元測試與 fixtures |
