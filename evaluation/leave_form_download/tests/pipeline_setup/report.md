# 流程測試（pipeline_setup）：休學申請表下載題（資源類），用假設的答案讓整條評測管線跑一次

**日期**：2026-11-13（同日第二輪：加了第 5 個案例 `complete_direct`，確認問題 1；第三輪：用結構化來源修好問題 1，重做 `complete_direct` 的隔離回推；第四輪：重做 `aca_link_only`，確認 c4；第五輪：用 `isolated-v3` 提示詞重做 `complete`、`wrong_form`、`verbose`，驗證 Bash 有沒有消失）
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

兩者都只碰了被允許的輸入檔與輸出檔，沒有讀 gold、鑰匙或任何其他檔案，**隔離的實質沒有被破壞**；它們的 trace 也都由 `check` 驗證通過。這兩份標「稽核 FAIL（字面違規）」。這個工作到目前為止用過的 14 個子代理（第 2 題三個、`tampered_v2` 一個、本題十個），11 個完全照規矩，3 個用了 Bash，**三個都是 v2 提示詞**：`complete` 第一次（Python 逐字檢查）、`complete_direct` 第一次與 `aca_link_only` 重做（heredoc 寫輸出檔再用一行 Python 確認能解析）。v3 提示詞的 3 個子代理都沒有用。

## 結果（只供看流程，不是評測結果）

| 案例 | 主張 | 有依據 | K1／K2（Keypoint 判斷） | Completeness／Hallucination | 答案為單位 P | 規則版 Accuracy |
|---|---|---|---|---|---|---|
| complete（稽核 FAIL） | 3 | 3（1.00） | relevant／relevant | 1.00／0.00 | **0.67** | 2/2 |
| aca_link_only | 4 | 4（1.00） | relevant／irrelevant | 0.50／0.00 | **0.25** | 1/2 |
| wrong_form | 3 | 0（0.00） | wrong／wrong | 0.00／1.00 | 0.00 | 0/2 |
| verbose | 13 | 13（1.00） | relevant／relevant | 1.00／0.00 | **0.15** | 2/2 |
| complete_direct 第一次（稽核 FAIL，修改前，原樣保存在 `complete_direct/first_run_before_sources/`） | 3 | **2（0.67）**，c3 連結沒依據 | relevant／relevant | 1.00／0.00 | 0.67 | 2/2 |
| **complete_direct 重做（修改後：證據帶 `sources`、回推規則 10 條）** | 3 | **3（1.00）**，c3 引自 `sources` | relevant／relevant | 1.00／0.00 | 0.67 | 2/2 |

規則與 Claude 都沒有不一致。`complete_direct` 第一次另有：**答對但沒依據的 keypoint：K2**，Context 句子召回 0.50；**重做之後 K2 不再被列為答對但沒依據**，有依據比例 1.00。Context 句子召回仍是 0.50：gold 的 K2 依據句在教務處頁面，這一題的證據只有表單本身，沒讀到那一頁，這是 Context 層的另一件事（連結是從表單的標記行來的），這次沒有處理。

**聚焦度（使用者選項 A 的預期）驗證了**：`complete`、`verbose` 的 Completeness 都是 1.00，只有「答案為單位 P」分得出差別（0.67 對 0.15）。`aca_link_only` 的 P（0.25）比 `complete` 低，因為它多講的 2 個主張（教務處頁面的位置與網址）不屬於任何 keypoint。最簡短、最聚焦的答案（只給連結）會得到 1.00，所以 P 的絕對值沒有意義（與前面討論一致）。

## 找到的問題（只記錄，沒有決定）

### 1. 網址主張的依據（已用第 5 個案例確認，並用「結構化來源」修好）

**問題**：`build_evidence` 把 `[live:src … url=…]` 標記行剝掉，網址另存到 `source_url` 欄位；回推規則要求引句必須逐字取自該項目的 `text`，`source_url` 不在 `text` 裡。結果：

| 情況 | 修改前 |
|---|---|
| 完整網址在頁面文字裡（`complete`，有 `get_page`） | 子代理引得到，supported，正確 |
| 網址只在標記行（`aca_link_only` 的 c4，教務處頁面自己的網址） | 引不到。子代理拿標頭行（只有標題與 subdomain）當引句判 supported，通過 `check`（逐字存在），但證明的是頁面標題不是網址，灌水（子代理自述不確定） |
| **網址只在標記行，而且是答案裡最重要的內容（`complete_direct`，真實 run 的形狀）** | **答對的連結被判沒依據**：有依據比例 0.67；K2 被列進「答對但沒依據的 keypoint」；Context 句子召回 0.50。真實系統看得到標記行裡的網址，所以這是評測這一側的偽陰性 |
| `resource_node` 把三張表單合成一則訊息 | `source_url` 只記到第一個標記（委託書那張），休學申請書的網址沒有保存 |

標記行被剝掉有理由（網址路徑裡的字，例如「退費」，會讓關於職掌的主張被誤判為有依據，T5），所以是兩個決定的衝突。

**做法（使用者選擇 C，2026-11-13）**：標記行仍然剝掉，但每個證據項目新增 `sources`：這個項目裡系統看到的每個網址，加上它前一行的名稱（label：`get_form 取得表單` 後面的標題，或 `get_page` 的頁面標題；被剝掉的純網址來源行也收進來，label 是「來源」「補充來源（…）」）。新增回推規則 10：答案裡的網址主張可以引用 `sources`，evidence 寫 `{"item", "quote", "from": "sources"}`，**quote 必須等於 sources 裡的一個完整網址**（正規化後精確比對：解開網址編碼、小寫主機、去掉結尾斜線與 `#`），由程式（`check_trace`）驗證；這個網址對不對得上答案說的東西，由子代理看 label 判斷；網址路徑裡的字仍然不算其他主張的證據；`from` 只能是 `sources`。
分工：「網址有沒有出現過」是確定的事，交給程式；「網址對應什麼」需要理解，交給子代理看 label。這樣編造的網址（差一個字元）會被程式確定退回，T5 的陷阱不會重現（引句必須是完整網址，不能只引網址裡的字）。

**結果**：`complete_direct` 重做（新的子代理，只拿修改後的 `trace_input.json`，提示詞不變、規則在輸入檔裡，稽核 PASS：3 次呼叫）：c3 引 `sources` 裡的完整網址，label 是「休學/保留學籍申請書」，`check` 通過；**有依據比例從 0.67 回到 1.00，K2 不再被列為答對但沒依據**。
**`aca_link_only` 重做（第四輪）**：c4（答案裡的教務處頁面網址）修改前拿標頭行當引句（灌水），修改後改引 `sources` 裡的完整網址（`from: sources`，label 是頁面名稱），`check` 通過。**分數沒有變**（有依據 4/4＝1.00、答案為單位 P 0.25、Completeness 0.50），變的是 c4 現在是用正當的方式得到的。修改前的檔案原樣收在 `aca_link_only/first_run_before_sources/`。
**沒有處理的**：(a) 〔第五輪已處理〕`complete`、`wrong_form`、`verbose` 原本是修改前產生的（9 條規則、沒有 `sources`），第五輪用新規則與 v3 提示詞重做了。(b) Context 句子召回仍是 0.50。(c) 只改了評測這一側；系統的答案本來就是對的。
測試：`test_stage3_prepare.py`（多個標記、`get_form`／`get_page` 的 label、純網址來源行、去重、沒有標記的項目）、`test_stage3_check.py`（完整網址有效並保留 label、差一個字元的網址無效且 supported 降級、路徑裡的字不能支持其他主張、網址的一部分無效、正規化、未知 `from` 值、舊的 `trace_input`（沒有 `sources`）不當掉、一般引句不變）、`test_skill_scripts.py`（`verify_run` 接受 `from: sources`、拒絕其他值）。

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

## 第五輪：用 `isolated-v3` 重做 `complete`、`wrong_form`、`verbose`

三個案例都用新規則（10 條、證據帶 `sources`）與 v3 提示詞（只准 Read 與 Write、不准 Bash）重做，三個全新的子代理。舊的檔案原樣收在各自的 `first_run_before_sources/`。

**v3 的驗證：三個都是 3 次呼叫（Read、Write、交回報告），稽核全部 PASS，沒有人用 Bash。** 樣本只有 3 個，但這三個案例的前一輪（v2）有 1 個用了 Bash，所以趨勢是對的；仍然只能說「沒有再發生」，不能說「保證不會」。

| 案例 | 版本 | 主張 | 有依據 | Completeness | 答案為單位 P | 答對但沒依據 |
|---|---|---|---|---|---|---|
| complete | v2 | 3 | 3/3 | 1.00 | 0.67 | 無 |
| complete | v3 | 3 | 3/3 | 1.00 | 0.67 | 無 |
| wrong_form | v2 | 3 | 0/3 | 0.00 | 0.00 | 無 |
| wrong_form | v3 | 3 | **1/3** | 0.00 | 0.00 | 無 |
| verbose | v2 | **13** | 13/13 | 1.00 | 0.15 | 無 |
| verbose | v3 | **9** | 9/9 | 1.00 | 0.22 | 無 |

**這一輪看到的兩件新事（只記錄，沒有決定）：**

1. **名稱與編號成對的主張被拆開了（`wrong_form`）**：答案說「休學申請書的名稱是『提早復學申請書』，表單編號 QP-T01-03-04」。v3 的子代理把「表單編號 QP-T01-03-04」單獨判 supported（證據裡確實有這個編號，是提早復學申請書的），子代理自述不確定，因為答案把它掛在休學申請書上，而證據不支持這個配對。結果：一個答錯的答案有依據比例是 1/3，不是 0/3（v2 那次是 0/3）。Keypoint 層不受影響（K1、K2 都 wrong）。
   這跟人員的「姓名、職稱、分機」是同一種問題：成對的識別資訊拆開後，單獨看每一半都能在證據裡找到，配對錯誤就被藏起來了。規則 6、7 只寫了人員。可以把規則 6、7 推廣成「成對的識別資訊（人與職稱、分機；表單名稱與編號；單位與電話）寫成同一個主張，要證據把同一個東西配同樣的另一個才算 supported」。待使用者決定。
2. **同一份答案，切出的主張數不同（`verbose`）**：v2 切成 13 個，v3 切成 9 個（例如 c4 把「攜帶證件、填妥申請書、送至註冊組」併成一個主張，c5 併了兩句）。答案、證據結構都沒變，只有提示詞版本與規則條數不同，P 就從 0.15 變成 0.22。這是「切法有彈性、穩定度沒量過」的實際數據（設計文件 13.3 的已知限制）：切法的雜訊會直接進到以主張為單位的數字。仍然不處理，記下來。

## 後續

- 問題 1 已用結構化來源處理（上面），`complete_direct`、`aca_link_only` 都已用新規則重做確認。
- **提示詞與稽核不一致（已處理，使用者選 A；第五輪驗證 v3 有效）**：`isolated-v2` 提示詞原文是「Do not run shell commands **other than** reading that one file and writing your one output file」，字面上允許用 shell 讀輸入檔、寫輸出檔；稽核卻只准 Read、Write、交回報告。3 個違規的子代理做的事（heredoc 寫輸出檔、用 Python 檢查自己的檔案）符合提示詞的字面，不符合稽核的字面。已把提示詞改成 `isolated-v3`：只准用 Read 讀輸入檔、Write 寫輸出檔，明講不准 Bash（包括寫檔、檢查引句、確認 JSON 能不能解析）。第一到第四輪的子代理用 `isolated-v2`，記錄原樣保留；第五輪三個子代理用 v3，**三個都沒有用 Bash**（見下）。
- `complete`、`complete_direct` 第一次的稽核違規：已決定接受並標註。
- Context 層對資源類題目的召回（gold 的依據句在教務處頁面、系統只讀了表單）：沒有處理，待決定。
