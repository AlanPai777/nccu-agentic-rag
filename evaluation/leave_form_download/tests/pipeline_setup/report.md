# 流程測試（pipeline_setup）：休學申請表下載題（資源類），用假設的答案讓整條評測管線跑一次

**日期**：2026-11-13（同日第二輪：加了第 5 個案例 `complete_direct`，確認問題 1）
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
| `complete_direct`（第二輪） | 答案與 `complete` 逐字相同，但證據是**直接走 `resource_node`** 的形狀：只有一則注入訊息、一張休學申請書，沒有 `get_page`（真實 2026-09-20 run 的節點順序） | 正確的連結只存在於標記行時，會不會被判沒依據 |

流程：`make_runs.py` → 階段 2 → 階段 3 `prepare` → **隔離回推**（5 個全新的 general-purpose 子代理，使用者批准；提示詞與 `tampered_v2` 逐字相同，只有路徑不同）→ `audit_subagent_tools.py` → `check` → `verify_run.py` → Keypoint 判斷（Claude Code）→ `score`。沒有呼叫 ollama，這一輪沒有對 nccu.edu.tw 發請求（現場查證在建 gold 時做過，見 `sources/live/live_check.md`）。

## 管線本身：走得通，但有一個稽核違規

| 項目 | 結果 |
|---|---|
| 階段 2、`prepare`、`check`、`verify_run`、`score` | 四份都正常；`check` 全部通過（逐字引用 4/4、7/7、0/0、13/13），沒有重疊警告 |
| 證據形狀 | E1＝`get_page` 的頁面；E2＝`resource_node` 的三張表單（`kind` 是 `HumanMessage`） |
| 子代理工具稽核 | `aca_link_only`、`wrong_form`、`verbose` 都是 3 次呼叫（Read 輸入、Write 輸出、交回報告），PASS。**`complete` 與 `complete_direct` 是 FAIL**，見下 |

**兩個稽核違規**（使用者決定：接受並標註，稽核維持嚴格；稽核改成違規時顯示完整指令，兩個案例的 `tool_audit.json` 都用新版重新產生）：

- `complete`：子代理用 Bash 跑了一段 Python，打開輸入檔與它自己的輸出檔，逐字檢查 `answer_span` 與引句是否在輸入檔裡。
- `complete_direct`：子代理沒有用 Write 工具，改用 Bash 的 heredoc（`cat > <輸出檔> <<'EOF'`）把 trace 寫進**被指定的輸出檔**，再用一行 Python 檢查那個檔案能不能被解析。**呼叫次數仍然是 3 次**（Read、Bash、交回報告），所以只看次數看不出來，稽核看的是工具名稱。

兩者都只碰了被允許的輸入檔與輸出檔，沒有讀 gold、鑰匙或任何其他檔案，**隔離的實質沒有被破壞**；它們的 trace 也都由 `check` 驗證通過。這兩份標「稽核 FAIL（字面違規）」。這個工作到目前為止用過的 9 個子代理（第 2 題三個、`tampered_v2` 一個、本題五個），7 個完全照規矩，2 個用了 Bash。

## 結果（只供看流程，不是評測結果）

| 案例 | 主張 | 有依據 | K1／K2（Keypoint 判斷） | Completeness／Hallucination | 答案為單位 P | 規則版 Accuracy |
|---|---|---|---|---|---|---|
| complete（稽核 FAIL） | 3 | 3（1.00） | relevant／relevant | 1.00／0.00 | **0.67** | 2/2 |
| aca_link_only | 4 | 4（1.00） | relevant／irrelevant | 0.50／0.00 | **0.25** | 1/2 |
| wrong_form | 3 | 0（0.00） | wrong／wrong | 0.00／1.00 | 0.00 | 0/2 |
| verbose | 13 | 13（1.00） | relevant／relevant | 1.00／0.00 | **0.15** | 2/2 |
| complete_direct（稽核 FAIL） | 3 | **2（0.67）**，c3 連結沒依據 | relevant／relevant | 1.00／0.00 | 0.67 | 2/2 |

規則與 Claude 都沒有不一致。`complete_direct` 另有：**答對但沒依據的 keypoint：K2**；Context 句子召回 0.50（其他案例是 1.00）。`wrong_form` 的規則版只能判 miss、不能判 wrong（沒有 `value_check`），與 Keypoint 判斷都是「沒命中」，所以沒有列為不一致（第 2 題同樣）。

**聚焦度（使用者選項 A 的預期）驗證了**：`complete`、`verbose` 的 Completeness 都是 1.00，只有「答案為單位 P」分得出差別（0.67 對 0.15）。`aca_link_only` 的 P（0.25）比 `complete` 低，因為它多講的 2 個主張（教務處頁面的位置與網址）不屬於任何 keypoint。最簡短、最聚焦的答案（只給連結）會得到 1.00，所以 P 的絕對值沒有意義（與前面討論一致）。

## 找到的問題（只記錄，沒有決定）

### 1. 網址主張的依據：標記行被剝掉之後，網址只剩 `source_url` 欄位（已用第 5 個案例確認）

`build_evidence` 把 `[live:src … url=…]` 標記行剝掉，網址另存到證據項目的 `source_url` 欄位；回推規則要求引句必須逐字取自該項目的 `text`，`source_url` 不在 `text` 裡。結果：

| 情況 | 結果 |
|---|---|
| 完整網址在頁面文字裡（`complete`，有 `get_page`） | 子代理引得到，supported，正確 |
| 網址只在標記行（`aca_link_only` 的 c4，教務處頁面自己的網址） | 引不到。子代理拿標頭行（只有標題與 subdomain）當引句判 supported，通過 `check`（逐字存在），但證明的是頁面標題不是網址；有依據在這個主張上是灌水的（子代理自述不確定） |
| **網址只在標記行，而且是答案裡最重要的內容（`complete_direct`，真實 run 的形狀）** | **答對的連結被判沒依據**：有依據比例 2÷3 ＝ 0.67；K2 被列進「答對但沒依據的 keypoint」，看起來像系統碰運氣答對；Context 句子召回從 1.00 掉到 0.50（K2 的依據句在教務處頁面，證據裡沒有），也在說「沒讀到」。子代理自述不確定，是照「網址本身不是證據」的規則判 unsupported |

**真實的系統其實是看得到這個網址的**：標記行是工具輸出的一部分，答案模型讀得到 `url=…`，連結並不是憑空編的。所以這是評測這一側造成的偽陰性，不是系統的問題。
**診斷被誤導**：資源類題目的核心內容就是連結，這個問題讓「有依據比例」、「答對但沒依據」、Context 召回三個診斷數字在這類題目上都指向錯的方向（以為是生成問題或檢索問題）。Keypoint 層不受影響（K2 判 relevant）。
另外：`resource_node` 把三張表單合成一則訊息時，`source_url` 只記到第一個標記（委託書那張，不是休學申請書）；`complete_direct` 因為只有一張表單才沒有受影響。

背景：標記行被剝掉有理由（第 2 題之前決定：標記行與只含網址的來源行不算證據，否則網址路徑裡的字，例如「退費」，會讓關於職掌的主張被誤判為有依據）。

**可行的做法（待使用者決定）：** 讓「答案裡的網址主張」可以引用證據項目的網址，但**引句必須等於其中一個完整網址**（不是子字串），這樣網址路徑裡的字仍然不能拿去支持其他主張。需要改 `build_evidence`（保留一則訊息裡所有標記的網址，不只第一個）、`check_trace`（接受引自 `source_urls` 的引句）、回推規則（新增一條）、補測試；之後 `complete_direct` 的隔離回推要重做。

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

- 問題 1 的做法：照上面的「可行的做法」改 `build_evidence`／`check_trace`／回推規則？或維持現狀、記為已知限制（資源類題目的網址主張與依據、Context 召回不可靠）？
- `complete`、`complete_direct` 的稽核違規：已決定接受並標註。
