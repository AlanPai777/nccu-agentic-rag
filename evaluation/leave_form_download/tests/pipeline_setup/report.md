# 流程測試（pipeline_setup）：休學申請表下載題（資源類），用假設的答案讓整條評測管線跑一次

**日期**：2026-11-13
**這不是系統的真實答案，下面的分數不能當評測結果。** 目的：檢查整條管線在第一題資源類題目上走不走得通，以及找出這類題目特有的問題。
答案是 Claude Code 寫的（`answers/`），證據用 `output/` 裡真實的快照（教務處頁面、moltke 表單原文）。`model`／`system_version`／`label` 都標「假設」。
不放 `runs/`，所以 `list_runs.py` 與之後的彙整都讀不到。`make_runs.py` 沒有單元測試。

## 做了什麼

證據照資源類題目的真實形狀組（從 `rag/agentic/tools/page.py`、`rag/agentic/tools/form.py`、`rag/agentic/nodes/resource.py` 讀出來的，**不是從真實的 run 記錄來的**）：

1. `get_page_tool` 讀教務處「休學-保留學籍-退學-提早復學」頁面：標頭、ledger 標記行、`[偵測到表單編號: …]`、全文。
2. `resource_node` 注入一則訊息：`[表單全文，…]` 加上頁面偵測到的**全部**三張表單（QP-T01-02-05、QP-T01-03-02、QP-T01-03-04），每張是 `get_form 取得表單 <標題>` + ledger 標記行 + 全文。

沒有重現 `contact_node` 的聯絡人清單與 `[偵測到辦公室]`（那需要 LLM 判斷辦公室，這題用不到）。

| 案例 | 答案 | 想看什麼 |
|---|---|---|
| `complete` | 一句話：名稱、編號、moltke 完整連結 | 流程走得通；K1、K2 都 relevant |
| `aca_link_only` | 名稱、編號、教務處頁面的網址，沒有 moltke 連結 | 2026-09-20 那次 Gemma 答案的失敗型態；K2 怎麼判 |
| `wrong_form` | 把「提早復學申請書」（QP-T01-03-04）當成休學申請書 | 真實會發生的混淆 |
| `verbose` | 同 `complete`，另附 5 條辦理流程（內容都來自教務處頁面） | 聚焦度：keypoint 滿分、主張精確率很低 |

流程：`make_runs.py` → 階段 2 → 階段 3 `prepare` → **隔離回推**（4 個全新的 general-purpose 子代理，使用者批准；提示詞與 `tampered_v2` 逐字相同，只有路徑不同）→ `audit_subagent_tools.py` → `check` → `verify_run.py` → Keypoint 判斷（Claude Code）→ `score`。沒有呼叫 ollama，這一輪沒有對 nccu.edu.tw 發請求（現場查證在建 gold 時做過，見 `sources/live/live_check.md`）。

## 管線本身：走得通，但有一個稽核違規

| 項目 | 結果 |
|---|---|
| 階段 2、`prepare`、`check`、`verify_run`、`score` | 四份都正常；`check` 全部通過（逐字引用 4/4、7/7、0/0、13/13），沒有重疊警告 |
| 證據形狀 | E1＝`get_page` 的頁面；E2＝`resource_node` 的三張表單（`kind` 是 `HumanMessage`） |
| 子代理工具稽核 | `aca_link_only`、`wrong_form`、`verbose` 都是 3 次呼叫（Read 輸入、Write 輸出、交回報告），PASS。**`complete` 是 FAIL**，見下 |

**`complete` 的稽核違規**：這個子代理用 Bash 跑了一段 Python，內容是打開輸入檔與它自己的輸出檔，逐字檢查 `answer_span` 與引句是否在輸入檔裡（`complete/tool_audit.json` 有記錄）。提示詞要求它「不要執行 shell 指令，只讀一個檔、寫一個檔」，所以字面上違規。但它只碰了被允許的兩個檔案，沒有讀 gold、鑰匙或任何其他檔案，**隔離的實質沒有被破壞**。它的 trace 之後也由 `check` 驗證通過。這一份的結果要標「稽核 FAIL（字面違規）」，要不要接受或重做，待使用者決定。其餘 7 個子代理（含第 2 題三個、`tampered_v2` 一個）都是 3 次呼叫。

## 結果（只供看流程，不是評測結果）

| 案例 | 主張 | 有依據 | K1／K2（Keypoint 判斷） | Completeness／Hallucination | 答案為單位 P | 規則版 Accuracy |
|---|---|---|---|---|---|---|
| complete（稽核 FAIL） | 3 | 3（1.00） | relevant／relevant | 1.00／0.00 | **0.67** | 2/2 |
| aca_link_only | 4 | 4（1.00） | relevant／irrelevant | 0.50／0.00 | **0.25** | 1/2 |
| wrong_form | 3 | 0（0.00） | wrong／wrong | 0.00／1.00 | 0.00 | 0/2 |
| verbose | 13 | 13（1.00） | relevant／relevant | 1.00／0.00 | **0.15** | 2/2 |

規則與 Claude 都沒有不一致。`wrong_form` 的規則版只能判 miss、不能判 wrong（沒有 `value_check`），與 Keypoint 判斷都是「沒命中」，所以沒有列為不一致（第 2 題同樣）。

**聚焦度（使用者選項 A 的預期）驗證了**：`complete`、`verbose` 的 Completeness 都是 1.00，只有「答案為單位 P」分得出差別（0.67 對 0.15）。`aca_link_only` 的 P（0.25）比 `complete` 低，因為它多講的 2 個主張（教務處頁面的位置與網址）不屬於任何 keypoint。最簡短、最聚焦的答案（只給連結）會得到 1.00，所以 P 的絕對值沒有意義（與前面討論一致）。

## 找到的問題（只記錄，沒有決定）

### 1. 網址主張的依據：標記行被剝掉之後，網址只剩 `source_url` 欄位（最重要，且有一半沒有測到）

`build_evidence` 把 `[live:src … url=…]` 標記行剝掉，網址另存到證據項目的 `source_url` 欄位；回推規則要求引句必須逐字取自該項目的 `text`，`source_url` 不在 `text` 裡。這在這題造成：

- **`aca_link_only` 的 c4**（答案裡的教務處頁面網址）：這個網址只出現在 E1 的標記行與 `source_url`，不在 E1 的 `text`。子代理自述不確定，**拿 E1 的標頭行（只有標題與 subdomain）當引句判 supported**。引句通過 `check`（逐字存在），但它證明的是頁面標題，不是網址，所以有依據比例 1.00 在這一個主張上是灌水的。
- **E2 的 `source_url` 只記到第一個標記**：三張表單合成一則訊息，只留第一個標記的網址（QP-T01-02-05 那張），其餘兩張（含 QP-T01-03-02）的網址都沒有保存。
- **`complete` 的連結主張有依據，是因為這個測試的證據形狀有 `get_page`**：完整的 moltke 網址出現在教務處頁面全文的 markdown 連結裡（E1 的 `text`），子代理才找得到逐字引句。
- **沒有測到的情況**：真實的 2026-09-20 那次 run 的節點順序是 `plan_node` → `resource_node`，**沒有 `get_page`**（`--stream` 記錄沒有任何工具呼叫）。在那種形狀下，正確的 moltke 連結只存在於標記行，會被剝掉，連結主張很可能被判 unsupported，即使答案是對的。**這一種需要再加一個案例（直接走 resource_node，不經 get_page）才能確認，需要使用者批准。**

背景：標記行被剝掉是有理由的（第 2 題之前決定：標記行與只含網址的來源行不算證據，否則網址路徑裡的字，例如「退費」，會讓關於職掌的主張被誤判為有依據）。所以這是兩個決定的衝突，不是單純的漏洞：要不要讓「答案裡的網址主張」可以引用 `source_url`，需要使用者決定。

### 2. 子代理的行為有些微變異

- `complete` 用 Bash 做檢查（上面的稽核違規）。
- `verbose` 的 c13「退費標準請參考學務處網頁」只引了連結文字「休（退）學退費標準」，子代理自述很薄；c11 的「其休學期間的修課紀錄」與證據的「之修課紀錄」只差一個字，子代理判 supported，引證據的原文。這些與第 2 題的推論句一樣，是 LLM 裁量的變異，沒有規則；不改規則，記為已知限制。

### 3. 與第 2 題的共同點

- 一個事實一個主張：`verbose` 的 13 個主張每個都是單一事實（名稱、編號、連結、5 條流程各切成 1 到 2 個），沒有重疊。
- 「表單名稱」那個無害的主張（c1）因為沒有對應 keypoint，使 `complete` 的 P 只有 0.67；「簡短完整」的答案反而比「只給連結」的 1.00 低（P 偏愛最短的答案）。

## 限制

- 答案、Keypoint 判斷都是 Claude Code 做的，我知道哪裡是故意寫錯的，判斷**不獨立**；這個測試只驗證機制。
- 證據形狀是從程式碼讀出來的，不是真實 run 的記錄；沒有 `contact_node` 的輸出。
- 每個案例一個子代理、一次執行；子代理只查了工具呼叫，看不到推理。
- 要確認「Gemma 真的跑得起來」只能靠真實的 run；這個測試只涵蓋評測這一側。

## 後續（都需要使用者決定）

- 問題 1：要不要加第 5 個案例（`complete` 的答案，但證據不含 `get_page`，模擬直接走 `resource_node`），確認連結主張會不會被判沒有依據？需要再開一個子代理。
- 問題 1 的取捨：答案裡的網址主張可不可以引用 `source_url`？
- `complete` 的稽核違規：接受（標註）或重做這一個子代理。
