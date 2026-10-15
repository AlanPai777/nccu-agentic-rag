# Phase J：查詢時即時抓取（Live Fetch）計畫

**日期**：2026-10-14
**狀態**：草案 v0.1 —— 尚未實作任何程式，尚未安裝任何套件，尚未對政大伺服器發出任何新請求
**分支（預計）**：`feature/live-fetch`（從 `main` 切出）
**程式碼位置（預計）**：`rag/live/`（新模組）＋ 少數既有檔案的小掛鉤（見 §3.5）
**總開關（預計）**：環境變數 `LIVE_FETCH=off|on`，預設 `off`（`shadow` 保留為日後選配，見 §5.1）
**變更紀錄**：v0.2（2026-10-14）—— ①`shadow` 簡化為日後選配，P1 改用不呼叫 LLM 的獨立檢查腳本；②User-Agent 定案沿用原始爬蟲的字串；③限速預設依原始爬蟲的實際設定與證據調整（全域併發 10→4）；④補記原始爬蟲實際留給網站端的資訊（§5.5）與 TLS 驗證的差異（§5.15）

---

## 0. 這份文件怎麼用

這是討論定案後的實作計畫，不是設計紀錄的流水帳。每個設計都依同一個格式寫：**做什麼 → 為什麼 → 考慮過的替代方案 → 風險與如何驗證**。

標示慣例（避免把推測當事實）：

| 標記 | 意思 |
|---|---|
| **（已查證）** | 本 session 讀過程式碼、資料或官方文件確認的事實 |
| **（使用者觀察）** | 使用者實際使用 america.gov 看到的現象，非公開文件 |
| **（推測）** | 依事實推論，尚無證據 |
| **（估計）** | 數字是估算，P0 要實測 |
| **（待驗證）** | 列入 §7 驗證項目 |

維護方式比照 `phase_h_agentic_rag_migration_plan.md`：每完成一個階段，回來更新該階段的狀態、實際遇到的問題、被推翻的假設，不讓這份文件變成一次寫完就過時的規劃稿。

---

## 1. 背景、問題與目標

### 1.1 問題

目前系統（`agentic_rag.py` ＋ `rag/agentic/`）的所有內容都來自本地快照：

| 資料 | 位置 | 快照時間（已查證） |
|---|---|---|
| 頁面全文 | `output/<subdomain>/extracted_texts.jsonl` | `aca` 爬於 2026-08-19（`output/aca/crawl_report.md`）；每頁時間在 `map.json` 的 `fetched_at` |
| 搜尋索引 | `rag/fts_proto3.db`（3.4GB） | 2026-08-26 建 |
| 聯絡人 | `output/office_contacts_index.jsonl` | 2026-08-25（記錄內的 `fetched_at`） |
| 表單 | `output/<sub>/supplementary_map.json` ＋ 補充 jsonl | 2026-08-21（`aca` 的 QP-T01-03-02 記錄） |

快照會過時，而且系統不知道自己過時。已有一個實例：`office_lookup_skill.py` 的註解記載教務長在 2026-08-25 從林啓屏更正為劉吉軒（已查證）。休學答案（`docs/evidence/2026-09-20_resource_query_run.md`）列出約 9 位具名承辦人與分機、申請期限、表單編號，這些都會隨時間變動（已查證）。

### 1.2 「保證最新」的定義（使用者定義，本計畫採用）

> 與官方網站的最新資訊一樣。例如 10/14 官網新出現一場講座，系統就能回答它。

精確化後的承諾，有三個必須明講的條件，否則「保證」會變成口號：

| 條件 | 意思 |
|---|---|
| **涵蓋範圍** | 我們監看的網站與區塊（登錄表，見 §5.13）。官網以外（臉書、外部報名表單）、沒列入監看範圍的頁面，系統不知道它出現了 |
| **延遲** | 查詢時現場抓取，延遲接近 0；快取命中時等於快取 TTL |
| **失敗時** | 現場失敗要明說「未能即時確認，資料時間 X」，不靜默退回舊資料 |

另一個不可消除的限制：**系統只能和官網一樣新**。官網本身可能過時或不一致（`docs/phase-f/` 記錄過來源頁面缺漏、跨頁資料不一致），這不是本計畫能解決的。

### 1.3 目標與非目標

**目標**
1. 查詢時，對 agent 實際讀到的頁面、表單、人員頁做現場確認，現場與快照不同就用現場。
2. 流程變動（表單 1 張變 2 張、蓋章站點 10 個變 12 個、人員異動）能沿著現有的依賴鏈自動反映，不需要改路由規則。
3. 能回答「今天／10/14 有什麼新內容、哪些處室有更新」這類時間查詢（新增項目）。
4. 每個答案揭露資料狀態（現場確認／與快照一致／快照後備）與時間。

**非目標（刻意不做）**
- 整批重爬、重新抽取、重建 FTS5（`rag/fts_proto3.db`）。使用者明確表示這不是目前要解決的。
- 把現場抓回的內容寫回語料庫或被 git 追蹤的 jsonl。
- 建立 dense／向量索引（與專案「導覽加整頁閱讀」的主軸不符）。
- 多行程共用速率限制、session 驗證、持久化 checkpointer（屬「上線前置」，另案）。
- 修改 `CourseLangChain-frontend`（P8 才需要，且是另一個 repo）。
- 複製 america.gov 的規模或內部架構（它的內部沒有公開）。

### 1.4 為什麼是「現場抓取」而不是「更新管線」

- 政大語料有 154 個子網域、約 20 萬筆記錄（`docs/architecture.md`）；`aca` 單站爬一次就要 84 分鐘（`crawl_report.md`）。不可能每天更新。
- 使用者的判斷：「不可能每天資料更新」，所以改成**查詢時只確認這次用到的頁面**。
- Phase F 已決定資料同步維持「手動、不定期」（`phase_f_planning_report.md` §2.16）。
- 現場抓取的負載取決於「熱門頁面數 × TTL」，不隨使用者人數增加（見 §5.3）。

### 1.5 與 america.gov 的關係（誠實區分）

| 類別 | 內容 |
|---|---|
| **已查證**（官方頁面與報導） | 2026-09-29 上線；GSA 營運；約 29,000 個政府網站；答案限官方來源並附連結；Gemini 經 Google 部落格確認，Grok 只有 Gebbia 在 CNBC 訪談中這麼說；回應可能以 prompt 雜湊快取最長 2 小時。官方 How it works 頁面**沒有**說明檢索機制、來源數量或速度 |
| **使用者觀察** | 問「今天的最新變化」，答案依日期整理（Oct. 13），每項附一句判斷，結尾附列表頁連結並邀請指定主題；30 秒內完成；Sources 面板 21 個來源（whitehouse.gov 20、senate.gov 1），其中約 7 個是網站區塊頁（Releases、News、Presidential Actions、Proclamations、Briefings & Statements、Videos、Statements of Administration Policy），約 13 個是單篇內容頁；面板列出的比答案文字引用的多 |
| **推測** | 一般問題走涵蓋全站的索引加一次 LLM 合成；即時問題走「依日期走訪網站的區塊頁，再讀近期項目」；是現場抓取還是近即時索引，從外部分不出來 |
| **我們借用的** | ①答案限官方來源並附連結；②「走訪區塊頁再讀近期項目」的即時問題形狀；③Sources 面板區分「查閱過的」與「引用的」；④短期快取的概念（我們改成頁面驗證結果的 TTL 快取，不快取答案） |
| **不借用的** | 全站索引、長 context 單次合成（我們的 Gemma4:31b 不適合）、其內部規模 |

---

## 2. 已定案決策總表

| # | 決策 | 內容 | 理由 |
|---|---|---|---|
| D1 | 現場與快照**同時取得並比對** | 不同用現場；相同用快照；現場失敗退回快照並標示 | 使用者決定。同時取得讓失敗時立刻有後備；比對順便量出快照漂移 |
| D2 | 只抓「需要的頁面」，不更新資料庫 | 現場結果只進旁路暫存快取 | 使用者決定。避免改寫被 git 追蹤的 jsonl、避免與離線 eval 糾纏 |
| D3 | 現有積木優先 | `httpx`＋Playwright＋`extract_html_bytes`／`extract_pdf`（組合 A）；Crawl4AI 當挑戰者（組合 B） | `requirements.txt` 已有 httpx、playwright、lxml、pdfplumber（已查證），零新依賴，且抽取格式與快照一致 |
| D4 | 工具介面不變 | Gemma 看到的仍是 5 個工具；現場與否由抓取器決定 | 符合專案「LLM 穩定度研究」主軸：不增加小模型的選擇點 |
| D5 | 路由維持標記驅動 | 現場文字 → 表單編號 → `resource_node`；表單文字 → 辦公室 → `contact_node` | 現有設計：標記由文字內容決定，所以替換會沿鏈自動傳遞（見 §4.3） |
| D6 | 注入今天日期 | state 新增 `today`（台北時區） | 「10/14」「今天」「本週」需要基準日才算得出視窗 |
| D7 | 「更新內容」＝**列表頁新增項目** | 不處理「既有頁面被編輯」 | 使用者決定。編輯偵測需要 `Last-Modified`／sitemap `lastmod`／歷史雜湊，待驗證後再議 |
| D8 | 單一請求逾時 60 秒 | 只代表「這一頁失敗」，該頁退回快照，其他頁照常 | 使用者同意。`httpx` 預設 5 秒、Playwright 導覽預設 30 秒（已知預設值），完全不設會讓卡住的連線使整題不結束 |
| D9 | 整題時間上限**不強制**，只發警告 | 門檻 30/60/120/300 秒（可調）→ 日誌 WARNING＋LangFuse 標籤＋SSE status | 使用者決定。先量測 p50／p95，再決定要不要加整題上限 |
| D10 | 速率限制必須有，且全程式共用 | 見 §5.5；保守起步（單網域並發 2／間隔 1 秒／全域並發 4），觀察無被限流再調高 | `robots.txt` 不是速率控制；限速避免被擋 IP；原始爬蟲的證據只支持約每秒 1 個請求的循序抓取 |
| D11 | User-Agent 沿用**原始爬蟲**的字串（選項 A）；不另行知會計中 | httpx 使用 `Mozilla/5.0 (compatible; NCCU-Edu-Crawler/1.0; +https://www.nccu.edu.tw) Academic research bot`；Playwright 先維持 Chromium 預設（與產生人員索引時一致） | 使用者決定。與先前全站爬取的身分一致，等於沒有新增任何識別。「不知會」列為延後決策（見 §8），P7（掃多處室）前再議 |
| D12 | MCP 分工：程式碼做確定性工作，LLM 做判斷，重資源做獨立服務 | 見 §5.18 | MCP 是打包與傳輸方式，不決定穩定度 |
| D13 | 分支＋模組並用 | `feature/live-fetch`＋`rag/live/`；spike 放 `experiments/live_spikes/` | 分支隔離過程、模組隔離程式碼；對既有檔案的改動限小掛鉤 |
| D14 | 開關 | `off`／`on`；P1 用獨立檢查腳本量測；`shadow` 保留為日後選配 | 使用者決定簡化：單人原型不需要 shadow；同樣的量測用不呼叫 LLM 的檢查腳本即可（見 §5.1） |
| D15 | 驗收「單次」 | 每階段端到端最多跑一次；不跑多次取平均 | 使用者決定：用量有限。故設計成大部分測試不需要 LLM（見 §5.19） |
| D16 | 驗收範圍先限「休學」 | 「10/14 哪些處室有更新」P7 之後跑一次看結果，有答案再討論 | 使用者決定 |

---

## 3. 大架構

### 3.1 現況流程（以「如何辦理休學」為例，全部本地）

```
Query「如何辦理休學」
  │
  ▼
plan_node ── router 關鍵字層命中「如何辦理／休學」→ query_type=procedure（不呼叫 LLM）
  │            _after_plan：procedure 與 knowledge 同走 "knowledge"
  ▼
rewrite_node（LLM）──▶ domain_router_node（本地關鍵字表／FTS5 票數 → subdomain_hint=aca）
  │
  ▼
agent_node（Gemma + 5 工具）
  │   search_texts ──▶ rag/fts_proto3.db（快照）──▶ judge 選 1 個候選 URL
  │   get_page(url) ──▶ output/aca/extracted_texts.jsonl（快照，grep 找 URL）
  │                      └ 全文含表單編號 → header 印 [偵測到表單編號: QP-T01-03-02, …]
  ▼
_after_tools：看到表單標記 ──▶ resource_node
  │   get_form(id) ──▶ supplementary_map.json（快照）──▶ moltke PDF 的快照文字
  │   抽站點／角色／核取方塊；_detect_offices（子字串＋LLM judge）→ [偵測到辦公室: …]
  ▼
_after_resource：看到辦公室標記 ──▶ contact_node
  │   OfficeLookupSkill ──▶ output/office_contacts_index.jsonl（快照）──▶ 姓名／分機
  ▼
回 rewrite_node ──▶ agent_node 判斷「夠了」──▶ synthesis_node（一次 LLM，流程手冊格式）
  ▼
self_eval_node（Stage 1 確定性檢查 → Stage 2 LLM 判斷）──▶ END
```

特性：整條鏈沒有任何網路請求；每個節點讀到的都是 2026-08 的快照；答案不揭露資料時間。

### 3.2 新版總覽（圖的結構不變，只在資料讀取層加一層，再新增一條 recent 路由）

```
                                 ┌────────────────────────────────────────────────────────┐
                                 │  rag/live/  資料讀取層（新）                             │
                                 │  fetcher：同時取得（現場＋快照）→ 抽取 → 正規化 → 比對   │
                                 │  cache：旁路 SQLite（不進 git）  ratelimit：全程式共用    │
                                 │  allowlist：只允許 *.nccu.edu.tw  ledger：資料狀態標記    │
                                 └───────▲───────────▲───────────▲───────────▲────────────┘
                                         │           │           │           │
Query ─▶ plan_node ──(時間意圖，新)──▶ recent_node(新)          │           │
           │                              │                      │           │
           ├─(knowledge/procedure)──▶ rewrite_node ─▶ domain_router_node ─▶ agent_node ─▶ tools
           │                                                       get_page / extract_links ┘
           ├─(resource)───────────▶ resource_node ── get_form（現場取得表單）──┘           │
           ├─(contact)────────────▶ contact_node ── 人員頁現場渲染（Playwright）───────────┘
           └─(compound)──────────▶ multi_sub_query_node
                         ↓（各路徑最後都回到）
                   synthesis_node（recency 專用格式，新）─▶ self_eval_node（Stage 1 新增資料狀態檢查）
                         ↓
                   SSE：status／sources（P8）
```

重點：
1. **圖的節點與標記路由不變。** 只有 `plan_node` 多一條 `recent` 出口，以及新增 `recent_node`。
2. **所有讀取都經過 `rag/live/` 的同一個窗口**：`get_page`、`get_form`、人員頁，各自在原本的函式內多一層委派。
3. **本地快照的角色**：找路（`search_texts`／`grep_texts` 仍查 FTS5 與 jsonl）、預測依賴鏈（§5.10）、現場失敗時的後備。

### 3.3 分層（決定每個套件放在哪裡）

| 層 | 工作 | 本計畫的選擇 |
|---|---|---|
| ① 抓取與渲染 | HTTP、JS 渲染、並行、瀏覽器池 | 組合 A：`httpx`＋Playwright；挑戰者 B：Crawl4AI |
| ② 抽取 | HTML→文字、PDF→文字 | **固定**：`extract_html_bytes`、`extract_pdf`（格式與快照一致是硬需求，見 §5.6） |
| ③ 發現 | 列表頁、sitemap、RSS | 登錄表＋列表頁解析（§5.13）；Trafilatura 的 sitemap／日期工具列為選配 |
| ④ 接到 agent | `@tool` 或 MCP | 抓取器是程式內函式，不經 MCP（§5.18） |

### 3.4 預計的模組結構

```
rag/live/
├── __init__.py
├── config.py        # 開關、TTL、限速、逾時、警告門檻（全部環境變數可調）
├── fetcher.py       # fetch_with_compare(url, kind)：同時取得、抽取、比對、模式分流
├── compare.py       # normalize()、structure_diff()：確定性比對（不呼叫 LLM）
├── cache.py         # 旁路 SQLite：URL→最近一次現場結果；singleflight
├── ratelimit.py     # 全程式共用的限速器（網域並發、最小間隔、全域並發、退避、斷路）
├── allowlist.py     # 網域白名單、私有 IP 阻擋、轉址檢查
├── ledger.py        # 資料狀態標記的產生與解析（build_ledger(messages)）
├── timeintent.py    # 時間意圖與日期視窗解析（today 為基準）
├── dates.py         # 民國／西元／無年份日期解析
├── registry.json    # recent_node 的登錄表（處室→列表頁）
├── recent.py        # recent_node 的邏輯（列表頁解析、視窗過濾、分組）
├── prefetch.py      # 預測性預抓
├── forms.py         # moltke 表單現場取得（viewdetail→goFile token→PDF）
├── contacts.py      # 人員頁現場渲染與職務解析
├── adapters/        # 抓取後端轉接器：httpx_playwright.py（A）、crawl4ai.py（B）…
├── _cache/          # （gitignored）SQLite 與暫存 PDF
└── _logs/           # （gitignored）差異日誌
experiments/live_spikes/   # 套件小測試、固定測試資料、check_chain.py（P1 的獨立檢查腳本）；不被正式程式碼 import
```

`rag/live/` 放在 `rag/` 底下，與 `rag/agentic/` 一致（`docs/architecture.md` 的 Future work 提到未來才會拆出，這次不動）。

### 3.5 對既有檔案的掛鉤（行號為 2026-10-14 讀到的版本）

| 檔案 | 位置 | 改動 |
|---|---|---|
| `rag/agent_tools.py` | `get_page`（121）、`_search_pages_for_url`（153）、`extract_links`（199，委派 `get_page`）、`get_form`（261，內部呼叫 `get_page(r["url"])`） | `LIVE_FETCH != off` 時委派 `rag.live.fetcher`；`get_form` 改走 `rag.live.forms`；快照讀取邏輯保留當後備 |
| `rag/agentic/tools/page.py` | `get_page_tool`（26） | header 加資料狀態標記；**不改既有的 `[偵測到表單編號]`、`[偵測到辦公室]` 標記** |
| `rag/agentic/nodes/resource.py` | `resource_node`（24） | 不改邏輯；它經 `get_form_tool` 取得表單，自動受惠 |
| `rag/agentic/nodes/contact.py` | `contact_node`（19） | 不改邏輯；它經 `OfficeLookupSkill` 取得人員資料 |
| `rag/skills/office_lookup_skill.py` | `dynamic_contacts_for_office`（447）、`_find_pages`（619）、`_load_contacts_index`（429） | 加現場渲染路徑，索引降為後備 |
| `rag/agentic/nodes/plan.py` | `plan_node`（38）、`_after_plan`（62） | 在複合偵測之後、分類器之前加時間意圖偵測；`_after_plan` 多一條 `recent` |
| `rag/agentic/state.py` | `AgentState`（41） | 新增 `today: str` |
| `agentic_rag.py` | `build_graph`（44）、`initial_state`（74） | 新增 `recent_node` 與其邊；`initial_state` 填入 `today` |
| `rag/agentic/nodes/synthesis.py` | `_SYNTHESIS_PROMPT`、`synthesis_node`（82） | `query_type=="recent"` 時用專用提示；附資料狀態揭露 |
| `rag/agentic/logic/self_eval_checks.py` | `stage1_checklist`（~86） | 新增：退回快照時答案必須揭露；recent 類不得出現步驟格式 |
| `rag/agentic/logic/office_detection.py` | `_detect_offices`（54） | 加內容雜湊快取（頁面內容沒變就不重呼叫 LLM） |
| `.gitignore` | — | 加 `rag/live/_cache/`、`rag/live/_logs/` |
| `server.py` | — | P8 才動（sources 事件）；本計畫未讀其細節 |

### 3.6 誰觸發現場抓取（與 Gemma 的分工）

| 觸發者 | 例子 | 現場抓取由誰決定 |
|---|---|---|
| **Gemma 的工具呼叫** | agent 呼叫 `get_page(url)`、`extract_links(url)` | Gemma 決定「讀哪一頁」（和現在一樣）；**是否現場由抓取器決定** |
| **程式的標記路由** | 頁面文字含表單編號 → `resource_node` → 抓表單；表單文字含辦公室 → `contact_node` → 抓人員頁 | 程式碼（Gemma 沒有否決權，沿用 §M D3/D6 設計） |
| **`plan_node` 的時間意圖** | 「10/14 哪些處室有更新」→ `recent_node` 抓列表頁 | 程式碼（確定性規則） |
| **導覽新頁面** | 現場列表頁的連結 → agent 再 `get_page` 點進去 | Gemma 決定點哪個連結；抓取器在快照沒有該 URL 時改為現場抓取 |

理由：維持「工具清單與決策面不變」，使小模型的穩定度研究不被新功能干擾；同時確定性的部分（表單、人員、列表頁）不依賴 Gemma 是否記得去抓。若要研究「Gemma 全權導覽現場網站」，那是 §5.18 的獨立實驗 J，不進產品路徑。

---

## 4. 休學流程完整對照

### 4.1 逐步對照

| # | 步驟 | 現況（純本地） | 新版（`on` 模式） |
|---|---|---|---|
| 1 | 分類 | `plan_node`：關鍵字命中 → procedure | **不變**（時間意圖偵測：無時間詞 → 不走 recent） |
| 2 | 改寫與子網域 | `rewrite_node`、`domain_router_node` | **不變** |
| 3 | 找候選頁 | `search_texts` 查 FTS5 快照，judge 選頁 | **不變**（快照負責找路） |
| 4 | 讀休學規定頁 | `get_page` 讀 jsonl 快照（2026-08-19） | `get_page` → `fetcher`：現場抓取＋快照同時取得、抽取、正規化、比對；不同用現場，相同用快照 |
| 5 | 偵測表單 | `extract_form_ids` 掃快照文字 | **同一支函式**，掃的是（現場或一致的快照）文字；標記格式不變 |
| 6 | 讀表單 | `get_form` 只查 `supplementary_map.json`，讀快照 PDF 文字 | `rag.live.forms`：現場取 `moltke…/link.jsp?viewdetail=<ID>` → 解析 goFile token → 下載 PDF → `extract_pdf`；新編號也能取；停用表單標記為已廢止 |
| 7 | 抽站點與辦公室 | `_extract_station_roles`、`_detect_offices`（子字串＋LLM judge） | **同一批函式**，輸入是現場表單文字；`_detect_offices` 加內容雜湊快取 |
| 8 | 查承辦人 | `contact_node` 讀 `office_contacts_index.jsonl` 並解析 | 對每個偵測到的處室，用 Playwright 現場渲染該處室人員頁（沿用 `fetch_office_contacts.py` 的做法），以「職務」解析；失敗才退回索引並標示 |
| 9 | 合成 | `synthesis_node`：流程手冊格式；連結由 LLM 在最後自己寫 | 同一個提示＋資料狀態揭露；來源與時間由程式依標記產生 |
| 10 | 自我評估 | Stage 1／Stage 2 | Stage 1 新增：退回快照時答案必須揭露；其餘不變 |
| — | 預抓 | 無 | 依快照預測依賴鏈，背景平行預抓並暖快取（§5.10） |

### 4.2 休學一次查詢的現場請求量（估計）

依 `docs/evidence/2026-09-20_resource_query_run.md` 的答案（約 10 個處室、約 9 位承辦人、3 張以內表單）推估。**這是估計，P0 要實測；先前說的「約 10 頁」低估了。**

| 網域 | 請求 | 說明 |
|---|---|---|
| `aca` | 約 3 | 休學規定頁、註冊組頁、教務長室頁 |
| `moltke` | **約 15（P0 實測）** | 3 張表單 ×（`link.jsp` → `login.formservice` → `viewDetail.formservice` → `viewFormDetail.jsp` → `df?<token>` 共 5 個請求） |
| `osa` | 約 4 | 住宿組、生僑組、原資中心、身心健康中心 |
| `cashier`、`lib`、`oic` | 各約 1 | 出納組、圖書館、國合處 |
| **合計** | **約 16～25** | 預測錯誤時的第二波補抓另計 |

每網域最小間隔 1 秒時，單一網域的最低耗時：`moltke` 6 個請求 ≥ 5 秒（moltke 若沿用現有腳本的 0.5 秒間隔，≥ 2.5 秒）、`osa` 4 個 ≥ 3 秒、`aca` 3 個 ≥ 2 秒。不同網域並行，單網域間隔的下限約 **5～6 秒**（估計）。人員頁走 Playwright，現有腳本每頁固定等待 2 秒讓 JS 載入完成（`SETTLE_MS=2000`，已查證）＋載入時間，所以人員頁較慢。再加上全域併發預設 4（§5.5），16～25 個請求的網路階段估計總計約 **8～12 秒**。這些數字全是估計，P0／P4 實測。

### 4.3 為什麼替換會沿依賴鏈自動傳遞

```
休學規定頁（現場文字）
   │ extract_form_ids（正規式掃文字，格式不變）
   ▼
表單編號集合 ──────────────▶ resource_node 對每個編號現場取表單
                                │ 表單文字
                                ▼
                  站點／角色／核取方塊 ＋ _detect_offices（子字串＋LLM judge）
                                │ 辦公室集合
                                ▼
                      contact_node 對每個辦公室現場讀人員頁 → 職務 → 姓名／分機
```

每一跳的輸入都是**上一跳的輸出文字**。只要每一跳都以現場文字為準，「頁面現在列出 2 張表單」就會讓 `extract_form_ids` 偵測到 2 個、`resource_node` 抓 2 張；「新表單的站點變 12 個」就會讓 `_detect_offices` 偵測出 12 個、`contact_node` 查 12 個。**圖與路由規則完全不用改。** 這是現有「標記驅動」設計帶來的紅利。

### 4.4 情境對照

| 情境 | 現況 | 新版 |
|---|---|---|
| **S0 官網沒變** | 答案內容同快照，不揭露資料時間 | 內容相同；多一行資料狀態（「現場確認，與快照一致，時間 X」）；多花網路時間 |
| **S1 表單由 1 張變 2 張** | 仍寫 1 張，語氣自信 | 偵測到 2 張，兩張都抓，synthesis 依既有規則 4 篩選相關者 |
| **S2 站點由 10 個變 12 個** | 仍列 10 個處室 | 偵測 12 個；不在 `office_contacts_index` 的處室靠處室目錄找頁面（§5.9） |
| **S3 註冊組組長換人** | 列出 8 月的名字 | 現場讀註冊組頁，以「職務：組長」解析出現任者 |
| **S4 舊表單連結消失／表單停用** | 仍引用舊表單 | moltke 頁顯示「此表格停用／查無此表格」→ 標記已廢止，不引用；改用現場頁面當前列出的連結 |
| **S5 moltke 暫時不可用（現場失敗）** | 不適用 | 該表單退回快照，標示「未能即時確認，資料時間 2026-08-21」；其餘照常 |
| **S6 現場內容與快照只差點擊數等動態欄位** | 不適用 | 正規化後判為相同，不誤報（§5.2） |

### 4.5 預期的答案揭露（示意，非實際輸出）

```
…（流程手冊內容，與現在格式相同）…

資料狀態（查閱時間 2026-10-14 10:32，台北時間）
・休學規定頁：現場確認，與快照一致
・QP-T01-03-02 休學／保留學籍申請書：現場確認，內容已變更（較 2026-08-21 快照）
・註冊組、住宿組、…：現場確認
・生僑組：未能即時確認，採用 2026-08-25 的資料
來源：
1. https://aca.nccu.edu.tw/…
2. https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-03-02
```

來源清單與「資料狀態」由程式依標記產生，不是 LLM 自己打（見 §5.11）。

---

## 5. 設計細節

### 5.1 模式與檢查腳本：`off`／`on`（`shadow` 日後選配）

**做什麼**

| 模式 | 答案來源 | 現場抓取 | 說明 |
|---|---|---|---|
| `off`（預設） | 快照 | 不抓 | 現有行為，零風險 |
| `on` | 現場（相同時用快照）；現場失敗退回快照 | 同時抓取並**等待完成** | 答案可能因現場內容而改變 |

- `recent_node` 路由只在 `on` 啟用（`off` 時時間查詢照現有流程走，行為與今天相同）。
- **P1 的量測用一支獨立檢查腳本**（`experiments/live_spikes/check_chain.py`，名稱暫定）：對休學鏈約 16 個 URL，同時取快照與現場、抽取、正規化、比對，輸出一張表（相同／不同／失敗、耗時、差異摘要）。**不呼叫任何 LLM，不需要任何模式開關。**
- `shadow`（保留為日後選配）：答案仍用快照，背景同時現場抓取並比對，只記錄不影響答案。只有在真的有很多學生使用、想先觀察再開 `on` 時才值得做。

**為什麼簡化（使用者決定）**
- 原本加 `shadow` 是為了「不改變答案的前提下量測漂移、失敗率、假差異」。但單人原型下，`on` 若有 bug，開發者立刻看得到答案異常，沒有誤傷學生的風險。
- 同樣的量測用檢查腳本就能做，而且**零 LLM 用量**，不需要在圖裡加模式，也不需要背景執行緒。
- `on` 緊接在 P1 之後的 P2 落地，不需要等到很後面。

**限制與補強**
- 檢查腳本量的是已知的休學鏈，不是「真實查詢實際讀到哪些頁」。這個缺口由 P2 的一次 `on` 端到端與 LangFuse trace 補上。
- 現場內容目前和快照一致時，無法證明「替換」那一段有效（官網現在沒變）。解法：固定測試資料注入（§5.19）。
- 無論哪種模式，答案與資料狀態都會進 LangFuse trace，所以「使用者看到什麼」永遠可追溯。
- 時間意圖查詢（「10/14 哪些處室有更新」）沒有快照版本可比，所以本來就只在 `on` 下運作。

**替代方案**：直接在圖裡做 `shadow`（現在不需要，見上）；完全不做量測就切 `on`（沒有基準數據，不採用）。

### 5.2 同時取得與比對（compare）

**做什麼**
1. 對一個 URL，**同時**啟動：本地快照讀取（毫秒級）、現場抓取。
2. 現場抓回後，用 §5.6 的同一支抽取器轉成文字。
3. 兩邊文字經 `normalize()` 後比對 `structure_diff()`。
4. 結果：**相同**→ 回傳快照文字，資料狀態「現場確認，與快照一致」；**不同**→ 回傳現場文字，資料狀態「現場確認，內容已變更」；**現場失敗**→ 回傳快照文字，資料狀態「快照後備」。
5. 差異摘要（表單編號集合增減、辦公室集合增減、分機集合增減、文字相似度）寫入日誌與 LangFuse。

**`normalize()`（必須）**
- 已知的假差異來源（已查證）：`osa` 的公告頁含「點擊數: 23193」這種每次瀏覽都會變的欄位。
- 規則：移除計數器行（`點擊數`〔`osa` 原資中心頁實測〕、`瀏覽數`〔`www.lib` 實測〕、`瀏覽次數`等）、壓縮空白、統一換行、忽略已知的動態區塊。規則清單放在 `compare.py` 的 `VOLATILE_PATTERNS`，由 P1 實測逐步補。
- 抽取器版本必須與建立快照時一致，否則會出現假差異（`phase_f_planning_report.md` 記錄過 NCCU-Crawler 與本 repo 的 `preprocess.py` 曾分岔；現在 `extract_html_bytes` 已存在於 `rag/preprocess.py:235`）。P1 要先抽樣確認「同一頁、同一抽取器、現場 vs 快照」在沒有內容變動時的相同率。

**為什麼**：使用者的決定。比對同時是「是否替換」的依據與「快照漂移」的量測。

**替代方案**：快照優先背景驗證（人員、表單可能先回舊的，答案已串流出去無法更正）；只用條件式 GET（要伺服器支援 ETag／Last-Modified，政大各站未驗證，列為可用時的優化而非主機制）。

**風險**：假差異（正規化不足）使每次都用現場，延遲增加但答案仍正確；假相同（正規化過度）會漏掉真實變動——因此規則只移除已確認的動態欄位，並在 P1 人工抽查差異。

### 5.3 暫存快取（cache）

**做什麼**
- 旁路 SQLite（`rag/live/_cache/live.sqlite`）＋暫存 PDF 檔，**gitignored**，**不併入語料庫**。
- 欄位：`url`、`kind`（page／listing／form／pdf／contact）、`fetched_at`、`status`、`etag`、`last_modified`、`raw_hash`、`text_hash`、`text`（正規化後）、`pdf_path`、`expires_at`。
- 預設 TTL（**估計值，待實測後調整**，全部可由環境變數調整）：一般頁 10 分鐘、列表頁 5 分鐘、人員頁 60 分鐘、表單 60 分鐘、PDF 24 小時。
- **singleflight**：同一 URL 同時有多個請求時，只發一次現場請求，其餘等待結果。

**為什麼**
- 對政大伺服器的負載取決於「熱門頁面數 × TTL」，不隨使用者人數增加（假設 500 個熱門頁、每小時驗證一次，約每天 1.2 萬次請求，平均不到 0.2 次／秒——這是示意，非實測）。
- 不寫回 jsonl：154 個被 git 追蹤的檔案被改寫會污染版本歷史，也讓離線 eval 失去可重現性。

**替代方案**：記憶體快取（行程重啟即失）；Redis（多一個服務，原型階段不必要）。

**風險**：多行程部署時各行程各有一份快取與限速器（屬上線前置，另案）；快取過大需要清理策略（P1 先做簡單的 TTL 過期清除）。

### 5.4 失敗處理與警告政策

**做什麼**
- **單一請求逾時 60 秒**（`httpx.Timeout(60.0)`；Playwright 導覽 `timeout=60_000`）。逾時算「這一頁失敗」：該頁退回快照，資料狀態標「快照後備」，其他頁照常；重試 2 次（指數退避，遵守 `Retry-After`）。
- **整題不設強制上限**（D9）。改成警告：現場階段耗時超過 30／60／120／300 秒（可調）時，各發一次警告——寫 WARNING 日誌、LangFuse 標籤 `live_slow_<秒數>`、SSE status「仍在確認官網內容（已 N 秒，M/K 頁完成）」。不中止任何請求。
- 其他失敗類型：Cloudflare 驗證頁（`is_cloudflare_page`）、空抽取、HTTP 4xx／5xx、轉址離開白名單——一律視為該頁現場失敗。
- **斷路**：同一網域連續失敗達門檻（預設 5 次）→ 暫停該網域一段時間（預設 5 分鐘），期間直接用快照並標示。

**為什麼**
- 一開始就設很短的整題上限會讓錯誤處理變得複雜（使用者原話：「不然出錯怎麼做」）。把「單頁失敗」與「整題體驗上限」分開：前者是技術邊界，後者先觀察。
- 前端沒有 SSE 閒置逾時（使用者確認）；伺服器端有 heartbeat（`phase_i_assistant_api_design.md`）；中間若有代理則未驗證（§7）。

**替代方案**：整題硬上限（待量測 p50／p95 後再決定）；完全不設單請求逾時（`httpx` 預設 5 秒、設為無限則一個卡死的連線讓整題不結束，故不採用）。

**風險**：無整題上限時，極端情況查詢會很久——靠警告與日後依數據調整。

### 5.5 速率限制（全程式共用）

**做什麼**
- `rag/live/ratelimit.py`：**行程共用的單例**，包在任何抓取後端轉接器的外面。
- 預設（全部可由環境變數調整）：

| 參數 | 預設 | 意思 | 依據 |
|---|---|---|---|
| 單一網域同時請求數 | 2 | 同一時刻最多 2 個請求在處理同一個主機（例如 `osa.nccu.edu.tw`） | — |
| 單一網域最小間隔 | 1 秒 | 對同一主機，新請求的起點至少隔 1 秒 | 原始爬蟲 `REQUEST_DELAY=0.5` 秒、循序抓取，實際每頁約 1 秒（`map.json` 時間戳，已查證）；moltke 腳本用 0.5 秒（已查證），moltke 可覆蓋為 0.5 |
| 全域同時請求數 | **4**（原型起步值，觀察後可調高） | 同一時刻最多 4 個請求在處理（跨所有主機） | 原始爬蟲 `config.py` 有 `MAX_CONCURRENCY=8`，但我在 `crawler.py` 找不到它被使用的地方，且 BFS 迴圈每頁 `time.sleep(_delay)`，看起來是循序的；所以**沒有證據顯示更高併發被政大伺服器容忍**。不同子網域是否共用同一台伺服器或防護設備未知（P0 驗證），共用時整體速率才是關鍵 |
| 每題 URL 預算 | 知識類 30；`recent_node` 另設 | 防止單題失控 | — |
| 429／503 | 遵守 `Retry-After`，指數退避 | — | `cpbae`（Azure 代管，23.99.124.39）在原始爬蟲中 92% 的請求（3683／4016）被 429 限流（`NCCU-Crawler/crawled_status.md`，已查證）；而原始爬蟲程式碼沒有任何 429／`Retry-After` 處理（已查證）。其他多數子網域記錄為「無 429／timeout」，失敗多為 404／400／500 |
| 斷路 | 見 §5.4 | — | — |
| 已知會限流的主機 | `rag/live/config.py` 的「主機覆蓋表」，例如 `cpbae.nccu.edu.tw` 預設更保守（暫定間隔 5 秒、並發 1，P0 觀察後調整）；P0 不拿它做壓力測試 | — | 同上：限流行為因主機而異，外部代管的主機門檻可能很低 |
| 快取命中 | 不計入 | — | — |

**「同時請求數」不是「每秒請求數」**：它是「同一時刻有幾個請求在飛」。休學約 16～25 個請求分散在約 6 個網域；單網域間隔與全域 4 共同決定耗時（估計 8～12 秒）。「10/14 哪些處室有更新」要掃 100 多個網域、每網域幾頁，每個網域不會被觸發單網域限制，全域 4 決定總耗時（若每個請求約 1 秒，約每秒 4 個，150 頁約 40 秒；估計）。起步保守的代價是多等幾秒，好處是不必猜政大伺服器的容忍度；P0／P1 若沒有看到 429／503／連線被重設，再把全域調高。

**為什麼**：`robots.txt` 是「允許與否」的訊號，不是速率控制。避免被擋 IP 要靠自己限速，且限速器必須是全程式共用，否則每題各自限速、總和失控。限速器獨立於抓取後端，換套件不必重寫（Crawl4AI 自帶分派器與退避，但不取代這一層）。

**`robots.txt`**：仍查，當作允許與否的檢查（有 `Crawl-delay` 就遵守；不允許的路徑跳過並記錄）。
- **已知**：`www.nccu.edu.tw/robots.txt` 內容為 `User-agent: *` ＋ `Allow: /`（使用者於 2026-10-14 自行查看，非本計畫實測）：全部允許，無 `Crawl-delay`、無 `Sitemap:`。**只代表 `www`；其他主機各自一份，未查證（§7）。**
- **實作**：用標準庫 `urllib.robotparser`（無新依賴），每個主機快取 24 小時。
- **規則（依 RFC 9309 的慣例）**：404 或沒有檔案 = 全部允許；有 `Disallow` = 跳過該路徑並記錄；伺服器 5xx 或連不上 = 暫時視為不允許，該主機退回快照並標示，不硬抓。
- **軟 404 陷阱**：有些 CMS 對不存在的網址回 200 加首頁 HTML（或轉址到首頁）。回應若不是純文字格式的 robots 內容（例如 `Content-Type` 為 `text/html`），視為「沒有 robots.txt」（全部允許），不把 HTML 當規則解析。

**User-Agent（使用者決定：選項 A）／不知會計中**：抓取器的 httpx 沿用**原始爬蟲**（`NCCU-Crawler/downloader.py`）的字串：

`Mozilla/5.0 (compatible; NCCU-Edu-Crawler/1.0; +https://www.nccu.edu.tw) Academic research bot`

理由：與先前全站爬取的身分一致，等於沒有新增任何識別，也不需要另外通知。Playwright 先維持 Chromium 預設 UA（與產生 `office_contacts_index.jsonl` 時一致，避免渲染差異；P4 觀察後再議）。UA 只在 `rag/live/config.py` 設一次。舊的一次性腳本（`fetch_moltke_forms.py`、`fetch_supplementary.py` 用 `NCCU-RAG-fetcher/1.0`）不需要改，它們不在查詢路徑上。

**原始爬蟲實際留給網站端（含計中）的資訊（已查證 `NCCU-Crawler` 的程式碼與文件）**

| 項目 | 內容 |
|---|---|
| 請求標頭 | 上面的 UA；`Accept: text/html,application/xhtml+xml,application/pdf,application/msword,*/*;q=0.8`；`Accept-Language: zh-TW,zh;q=0.9,en;q=0.8` |
| 識別能力 | UA 內的 `+https://www.nccu.edu.tw` 指向**學校首頁**，不是專案頁或聯絡方式，所以網站管理者看得出是「學術研究用的機器人」，但**無法循此聯絡到你** |
| 來源 IP | 取決於當時在哪個網路執行（我看不到，未知） |
| 速率 | 每頁間隔 0.5 秒、循序抓取；實際約每秒 1 頁；規模為 154 個子網域、約 20 萬筆頁面 |
| `robots.txt` | **從未讀取**（`NCCU-Crawler` 的 `*.py` 內完全沒有 robots 處理）。`www` 目前內容是 `Allow: /`（使用者查看），所以對該主機沒有影響；其他主機未知 |
| sitemap | **有處理，但方式有限**：`discover_sitemap()` 在 BFS 前對每個種子嘗試 `/sitemap.xml` 與 `/sitemap_index.xml`（固定兩個位置），解析後把網址預先放進佇列（`crawler.py:222`、`WORKFLOW.md`；已查證）。限制：從不讀 `robots.txt` 的 `Sitemap:` 行（所以位置不同的 sitemap 會漏掉）；非 XML 或壓縮檔解析失敗就略過；找到第一個有網址的就停 |
| 429 限流 | `cpbae`（Azure 代管）92% 失敗為 429；爬蟲沒有 429 處理，只能事後用 `--retry-failed` 重跑（已查證） |
| TLS 驗證 | `downloader.py` 的 `httpx.Client(..., verify=False)` **關閉了憑證驗證**（見 §5.15：本計畫不沿用） |
| 通知計中 | 在 `NCCU-Crawler` 與本 repo 的文件中**找不到任何通知或許可的紀錄**；若有其他管道（口頭、郵件）我看不到 |

**風險**：多行程需要共用儲存（Redis 或檔案鎖）——上線前置；P7 掃多處室前先從 2～3 個網域試。

### 5.6 現場抽取：HTML 與 PDF

**做什麼**
- HTML：`rag.preprocess.extract_html_bytes(html_bytes, url)`（保留 markdown 連結、解碼 Cloudflare email、依各站 CMS 選內容區、移除 `nav／header／footer／aside`）。抓回後先用 `is_cloudflare_page(html_bytes)` 擋驗證頁。
- 需要 JS 渲染的頁面（人員頁）：Playwright，`wait_until="load"`＋固定等待（沿用 `fetch_office_contacts.py` 的 `SETTLE_MS=2000`）。**不用 `networkidle`**：該腳本註解記載 `tsc.nccu.edu.tw` 與 `cids.nccu.edu.tw` 會在 `networkidle` 下無限期掛住（已查證）。
- PDF：`rag.preprocess.extract_pdf(path)`，它吃檔案路徑，所以寫到暫存檔（`rag/live/_cache/`）。**現場路徑不做 OCR**（tesseract 很慢）：圖片型 PDF 標示「無法即時解析」並退回快照。

**為什麼**：現場文字必須與快照同格式，否則表單編號正規式、markdown 連結、辦公室標記都會悄悄失效；也不會出現「抽取器不同造成的假差異」。

**替代方案**：改用套件自帶的 Markdown（Crawl4AI／Jina Reader／Firecrawl）——格式不同，標記可能失效，只當對照（§5.17）。

**風險**：固定 2 秒等待對慢站可能不足、對快站是浪費；可考慮改成等待特定選擇器（待驗證）。`preprocess` 版本漂移（見 §5.2）。

### 5.7 表單現場取得（moltke）

**做什麼**（依 `fetch_moltke_forms.py` 已查證的流程）
1. `GET https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=<表單編號>`。
2. 解析：表格列取得 `表單名稱／表單描述／表單關鍵字／承辦單位`；`a[href="#"]` 的 `onclick="goFile('<token>')"` 取得下載代碼。
3. 頁面含「查無此表格」或「此表格停用」→ 標記**已廢止**，不引用。
4. 選 PDF（中文優先）→ `GET …/df?<token>`，確認 content-type 為 PDF（或大小 ≥ 500 bytes）→ 暫存檔 → `extract_pdf`。
5. TLS：沿用現有的預設驗證加 `OP_LEGACY_SERVER_CONNECT`（moltke 使用舊式 TLS 重新協商，OpenSSL 3 預設擋；**驗證仍開著**）。
6. 任何編號都能取（`FORM_IDS` 只是當初的爬蟲清單，不是限制；P0 實測：休學頁偵測到的 3 個編號都能取得；是否對所有編號通用，P3 驗證）。
7. **moltke 以伺服器端 session 串起這 5 個請求**：最後的 `viewFormDetail.jsp` 網址不帶表單編號，內容取決於前面轉址時建立的 session（cookie）。因此**平行抓多張表單時，每張表單必須用獨立的 cookie jar／client**，否則 session 狀態會互相覆蓋、取到別張表單。固定測試資料重播時要依 `manifest.json` 的順序還原整條轉址鏈。

**為什麼**：表單決定整條鏈（站點→辦公室→人員），而現有 `get_form` 只查快照的 `supplementary_map.json`，新編號會得到「Form not found」。

**同編號換新版**：重新下載 PDF，比對雜湊（`token` 是否隨版本改變尚未知，P3 驗證）。

**只放暫存快取**（D2）。圖片型 PDF 不 OCR。

**風險**：moltke 的 `goFile` token 兩步取得的耗時與穩定度未測；moltke 暫時不可用 → 退回快照並標示（情境 S5）。

### 5.8 表單連結的變動與沒有編號的連結

**現況（已查證）**：休學頁以 markdown 連結參照表單，**編號在 URL 裡**：`[休學/保留學籍申請書](https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-03-02)`。`extract_form_ids` 的正規式 `QP-[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+` 掃的是全文，所以連結 URL 裡的編號也能偵測到。

**變動情境與處理**

| 情境 | 處理 |
|---|---|
| 新增連結，編號不同 | 現場頁面文字含新編號 → 偵測 → `forms.py` 現場取得 |
| 舊連結失效（404）或表單停用 | 視為該表單失敗／已廢止；以現場頁面**目前列出的**連結為準；快照只當提示 |
| **新連結沒有編號**（例如直接放 PDF 連結） | 現有偵測會漏。新增第二個偵測：現場頁面中指向文件的連結（`.pdf`、`.doc(x)`、`.odt`，或錨點文字含「申請書／申請表／表」），同網域白名單內，下載後解析，再跑 `extract_form_ids` 與站點抽取 |
| 表單搬到別的主機 | 白名單允許的 `*.nccu.edu.tw` 內照上一條處理 |

**為什麼**：表單是依賴鏈的樞紐，這是使用者特別點出必須現在考慮的問題。

**風險**：非 PDF 格式（ODT／DOCX）目前兩邊都沒有解析器（`phase_f_planning_report.md`），現場路徑先標示「無法解析」並退回；Docling／MarkItDown 列為對照（§5.17）。

### 5.9 人員查詢：以「處室＋職務」為單位，現場渲染

**做什麼**
- `contact_node` 對偵測到的每個處室：取得該處室人員頁網址（優先用 `office_contacts_index.jsonl` 該筆記錄已有的 `url`；不在索引中的處室，用 `domain_router._keyword_table()`（433 筆名稱、144 個子網域）找子網域，再從該子網域首頁導覽；全新設立的單位從校首頁行政單位目錄導覽）。
- 用 Playwright 現場渲染（沿用 `fetch_office_contacts.py`：`load`＋2 秒等待；`is_cloudflare_page`；`extract_html_bytes`），再交給現有 `parse_office_contacts`。
- **以職務查**：問的是「註冊組組長是誰」，不是「某某人現在在哪」。所以人員調動時答案自然不再列出舊人；快照裡的名字只當提示，不當答案來源。
- 找不到該職務（空缺或改版）：答案寫「查無該職務，請洽處室」，**不退回快照的舊名字假裝確認**。
- 並行：一個瀏覽器、多個 context（Playwright 官方建議做法；context 崩潰會拖垮同一行程內其他 context，所以池要有重啟機制），受 §5.5 限速約束。
- 現場失敗才退回 `office_contacts_index.jsonl`，並標示其 `fetched_at`。

**為什麼**
- 使用者在 Phase F Step 0c 決定：聯絡人頁容錯率低，靜態抓取抓不到 JS 局部注入造成的部分缺漏，所以 399 個 URL 全部用 Playwright（`phase_f_planning_report.md`）。
- 以職務查可避免「追蹤一個已調走的人」。

**URL 漂移**：處室改版後舊 URL 回 404、轉址或空殼頁，一律算失敗並標示，不算「已確認」；之後再考慮從處室首頁重新導覽找新位置。

**風險**：休學約 10 個處室＝約 10 次渲染（耗時 6～10 秒，估計）；`parse_office_contacts` 的 labeled 層遇到 fallback 會呼叫 LLM（`_llm_extract_contacts`），所以以頁面內容雜湊快取結果；多行程時瀏覽器池要隔離。

### 5.10 預測性預抓

**做什麼**：抓取器收到某頁的讀取請求時，依**快照**預測後面會用到什麼——「這頁連到表單 QP-T01-03-02，表單提到哪些處室」——並在背景同時現場抓這些表單與處室頁，暖好共用快取。

```
沒有預抓（循環等待）：
  agent→get_page(休學頁) ──▶ [現場抓 頁] ─▶ resource_node→get_form ─▶ [現場抓 表單 ×N]
                                                 ─▶ contact_node ─▶ [現場抓 處室頁 ×10]
  （每一波等上一波完成）

有預抓（快照預測鏈、同時開跑）：
  agent→get_page(休學頁) ─▶ [現場抓 頁]
                         ╰▶ 背景：[表單 ×N] [處室頁 ×10]   ← 依快照預測，同時抓
  之後 resource_node／contact_node 要資料時，快取已暖，直接命中
  若現場頁面其實多了一張新表單／多了處室 ─▶ 快取沒有 ─▶ 才補抓（第二波）
```

**與「同時取得並比對」的差別**：同時取得是**同一頁**的現場與快照同時；預抓是**後面才會用到的不同頁**提早開始。兩者互補。

**為什麼**：循序抓取的延遲會逐跳累加；快照對依賴鏈的預測在「沒變」的常見情況下幾乎全中，所以常見情況只需一波。

**風險**：預測錯會多抓沒用到的頁面（對政大伺服器多一點負載、用掉速率額度）——受 §5.5 的每題預算約束，且只在已知熱門鏈（例如休學）啟用；P5 才做，先量 P2～P4 的未預抓基線。

### 5.11 來源帳本（ledger）與資料狀態揭露

**做什麼**
- 每個被讀取的來源在回傳文字的 header 帶一行標記，例如：
  `[live:src url=<URL> kind=page status=live_same checked=2026-10-14T10:32 snap=2026-08-19T12:48]`
- `status` 取值：`live_same`（現場確認、與快照一致）、`live_changed`、`snapshot_fallback`（現場失敗）、`snapshot_only`（`off` 模式）、`live_new`（快照沒有的頁面）、`discontinued`（表單停用）。
- `rag/live/ledger.py` 的 `build_ledger(messages)` 從 `state["messages"]` 解析這些標記，產生：答案末尾的「資料狀態」段、來源清單（連結由程式產生，不是 LLM 打）、P8 的 `sources` SSE 事件。
- `self_eval` Stage 1 新增檢查：任何 `snapshot_fallback` 來源，答案必須揭露；`recent` 類答案不得出現步驟格式（`answer_quality_findings.md` 建議過的形狀檢查）。

**為什麼用「標記行」而不是 state 欄位**
- 符合現有架構：路由本來就靠 messages 內的標記（`_FORM_MARKER_RE`、`_OFFICE_MARKER_RE`）。
- 避免 state 的 reducer 問題：用 `Annotated[list, operator.add]` 的欄位會在同一 `thread_id` 的多輪對話中累加而不是重置；`compaction.py` 又會 `RemoveMessage` 掉整輪的 messages，標記隨之自然清除。
- 不必改 state schema 與 compaction。

**替代方案**：state 欄位＋自訂 reducer（較複雜）；行程內 contextvar（LangGraph 節點的執行緒傳遞行為未驗證）。

**風險**：標記格式一旦被其他節點誤解析就會影響路由，所以格式要與既有標記互不相交，並加單元測試。

### 5.12 今天日期注入與時間意圖

**做什麼**
- `AgentState` 新增 `today: str`（`YYYY-MM-DD`，`zoneinfo.ZoneInfo("Asia/Taipei")`）；`initial_state()` 每輪填入（`server.py` 也呼叫它，所以多輪對話每輪重新計算）。測試可用環境變數 `LIVE_TODAY` 覆蓋。
- `rag/live/timeintent.py` 的 `detect_time_intent(query, today, snapshot_date)`：

| 偵測 | 例 | 處理 |
|---|---|---|
| 相對時間詞 | 今天、昨天、本週、這週、最近、近期、剛剛、最新 | 走 `recent` |
| 明確日期，且視窗終點 > 快照日期 | 「10/14」、「10月14日」、「115年10月14日」、「2026年10月14日」 | 走 `recent` |
| 明確日期，早於快照日期 | 「5/26 的公告」 | 先走本地，再現場確認 |
| 無年份日期 | 「10/14」 | 以 `today` 的年份為準 |

- 位置：在 `plan_node` 的複合偵測之後、既有分類器之前，與複合偵測相同的「確定性優先」風格；`_after_plan` 多一條 `recent`。

**為什麼**：快照停在 8 月，晚於快照日期的內容本地搜尋不可能找到，這種查詢應直接現場找；時間詞判斷用確定性規則，不依賴 Gemma。

**風險與限制**
- 「明天有什麼講座」問的是**活動日期**，不是**發布日期**。v1 只處理發布日期（D7），以發布時間近似，由 synthesis 讀內文判斷活動日期；此為已知限制。
- `snapshot_date` 的來源：各子網域的 `map.json` `fetched_at` 或 `crawl_report.md`；取保守值（最舊）。

### 5.13 `recent_node`：近期項目與「10/14 哪些處室有更新」

**做什麼**

```
plan_node：解析時間視窗 [2026-10-14 00:00, 23:59 +08:00]、範圍=全部處室、類型=列舉
   ↓ recent_node
 1 登錄表：處室 → 列表頁網址清單（registry.json）
 2 平行抓取（§5.5 限速）→ 抽取（§5.6）
 3 解析項目 (標題, 日期, 網址)
 4 篩出落在視窗內的項目 → 依處室分組
 5 日期缺失的項目 → 抓內頁補日期（有預算上限）
 6 注入一則 HumanMessage：[即時近期項目 …視窗…查閱時間…涵蓋…]＋項目表＋資料狀態標記
 7 回到 rewrite_node（與 resource／contact 相同：agent 仍可點連結追內文）
 8 synthesis 用 recency 專用格式；輸出涵蓋統計與失敗清單
```

**登錄表（`registry.json`）**
- 處室名單：`domain_router._keyword_table()`（來自 `office_contacts_index.jsonl`，433 筆、144 個子網域，已查證）。
- 列表頁候選：用 `map.json` 的 URL 樣式（「最新消息」、「公告」、`news`）找出，再現場確認真的是列表頁，標 `verified`。**不能用 `child_count` 自動偵測**：實測 `aca` 前幾名是 Joomla 分頁頁（`…?start=24`，子頁 500～600）、`osa` 前幾名是單篇文章頁（數字被截在約 299）——該欄位被全站共用連結區塊污染（已查證）。
- 核心單位用人工校正覆蓋。第一版：核心處室加少數院系；P7 擴大。
- 格式用 JSON（不引入新依賴）。

**列表頁項目解析**
- 先用確定性規則：對抽取後的 markdown 文字，找同網域連結，於其前後數行內找日期。`osa` 公告內頁的 meta 行長這樣：`發佈: 2025年05月26日 | 點擊數: …`（已查證）；`aca` 最新消息頁約 61% 在前 400 字可偵測到日期（205 筆中約 125 筆，已查證）。
- 抽不到足夠項目時才交給 LLM（沿用 `_llm_extract_contacts` 的模式）；日期缺失的項目抓內頁補。
- 日期格式：民國（`115/10/14`、`115年10月14日`，年＋1911）、西元（`2026年10月14日`、`2026/10/14`）、無年份。時區台北，日粒度。

**分頁與置頂**：列表常有 `?start=N` 分頁與置頂舊公告，不能看到第一筆舊的就停。規則：逐頁掃，直到「整頁沒有視窗內項目，且已出現足夠多的舊項目」才停，並設頁數上限。

**輸出的誠實涵蓋**：「已檢查 N 個列表頁（涵蓋 K 個處室），M 個處室有 10/14 的新內容；P 個無法檢查（列出）」。**沒檢查到的處室絕不寫成「沒有更新」。**

**重複查詢**：結果以（視窗、登錄表版本）為鍵、TTL 5 分鐘共用快取並 singleflight。

**為什麼**：america.gov 的使用者觀察樣本顯示，即時問題是「走訪網站區塊頁再讀近期項目」（§1.5）；這與本專案「導覽加整頁閱讀」同型。「哪些處室有更新」的資訊就在各處室列表頁上。

**風險**：登錄表涵蓋範圍就是承諾範圍；列表頁可能靠 JS 渲染、無日期、格式各異；掃描量大（P7 先從 2～3 個網域試，並在擴大前重新評估 D11）。「更新」只算新增項目（D7）。

**驗證**：抽 5～10 個處室人工核對視窗內的項目——程式自己的結果是循環論證。

### 5.14 `recent` 路徑的答案形狀

**問題**：`_SYNTHESIS_PROMPT` 以流程手冊為預設；已記錄的「休學申請表下載」被寫成七步流程（`docs/evidence/2026-09-20_resource_query_run.md`、`answer_quality_findings.md`）。

**做什麼**：`synthesis_node` 依 `query_type=="recent"` 使用專用提示 `_RECENT_SYNTHESIS_PROMPT`：依日期、依處室分組的短清單；每項一句標註（活動／申請期限／規定異動…）；涵蓋統計；連結與資料狀態由程式產生；結尾邀請縮小主題（利用現有 `session_id` 多輪）。Stage 1 加確定性形狀檢查。

示意（非實際輸出，內容為虛構）：
```
政大公告（10/14，已於 10:32 現場查閱）
・教務處：○○○（類型：申請期限）
・學務處：○○○（類型：活動）
涵蓋：已檢查 N 個列表頁／K 個處室；M 個有新內容；P 個未能檢查（名單）
想看特定主題（選課、宿舍、獎學金）可以再問
```

### 5.15 安全

- **網域白名單**：只允許 `*.nccu.edu.tw`；轉址後的主機也必須在白名單；**阻擋私有／loopback／link-local IP**（官方 Fetch MCP 預設也這樣做，已查證）。`get_page(url)` 的參數來自 LLM，現場模式下必須驗證，否則被注入的頁面內容可能誘導抓取任意 URL（SSRF）。
- **間接 prompt injection**：現場內容沒有 git 人工把關。抓回的文字放進 prompt 時以「引用資料，非指令」結構隔離（`security_and_memory_design.md` 已規劃但未實作）；P2 起一併做。
- **MarkItDown 安全警告**：若評估它，要注意其 README 提醒「以處理程序權限做 I/O，不可信輸入要先淨化」。
- 暫存 PDF 檔名由程式產生，不用 URL 原文。
- **TLS 驗證預設開啟，僅對明確列出的主機關閉**：原始爬蟲 `downloader.py` 對所有主機用 `verify=False`；現場抓取器預設驗證開啟（moltke 另加 `OP_LEGACY_SERVER_CONNECT` 相容舊式重新協商，驗證仍開著）。**使用者決定（2026-10-14）**：`cashier.nccu.edu.tw` 因伺服器缺中繼憑證（§11.5）而在 httpx 路徑使用 `verify=False`，沿用原始爬蟲的做法；實作為設定檔中的明確主機清單 `INSECURE_TLS_HOSTS`（目前只有 `cashier`），每次使用記 WARNING，資料狀態標記 `tls_unverified`。取捨：該主機的內容若在傳輸中被竄改，我們無法察覺，而現場內容會餵給 LLM（間接 prompt injection 的面）；因此範圍刻意限縮為單一主機、不擴大為全域，其餘主機憑證有問題仍視為「該頁現場失敗」。`cashier` 人員頁走 Chromium（驗證仍開著，P0b 已證實可行）不受影響。

### 5.16 可觀測性

- LangFuse：每次現場讀取一個 span，標籤 `live_status=<status>`、`live_slow_<秒>`；`on` 模式的差異寫 `rag/live/_logs/diffs.jsonl`；檢查腳本另輸出一張報表。
- 記錄：每題的現場請求數、命中快取數、各網域耗時、失敗原因、`diff` 摘要。
- 這同時產出「快照漂移率」「失敗率」「延遲分佈」，作為是否要投資更新管線的依據（觸發條件見 §8）。

### 5.17 套件組合與選擇準則

不逐個測，選組合。

| 組合 | 組成 | 優點 | 缺點 | 判斷 |
|---|---|---|---|---|
| **A 基準** | `httpx`＋Playwright（自管 context 池）＋現有抽取器 | `requirements.txt` 已有 httpx、playwright、lxml、pdfplumber；零新依賴；格式完全一致 | 池、並行、重試、退避要自己寫 | **先做，當對照** |
| **B Crawl4AI（函式庫）** | Crawl4AI 當渲染與並行，抽取仍用我們的 | Apache-2.0；v0.9.4（2026-09-23）；`arun_many`、記憶體自適應分派器、預熱瀏覽器池、快取模式、429／503 退避、持久 session（均為 README／文件所述，已查證） | 新依賴；能否取得原始 HTML 待驗證；版本變動快；中文表現未知 | **主要挑戰者** |
| C Crawl4AI（Docker） | B 做成獨立服務（REST／MCP） | README 記載 REST 端點與 MCP；隔離、可共用 | 多一個服務、token、網路躍點；其 `/pdf` 端點用途不明；「支援圖片」未查證 | B 通過再評估 |
| D Browserless | 專用瀏覽器池，Playwright 連線 | 池與佇列成熟 | SSPL 授權待確認；與 B 重疊 | 候補 |
| E Jina Reader 自架 | URL→Markdown | 簡單；含 PDF | 輸出格式與我們的抽取器不同 | 只當對照 |
| F Firecrawl 自架 | | 功能多 | AGPL；多容器、資源需求高；缺託管反爬（對本專案無意義） | 暫不測 |
| G Lightpanda | CDP 相容輕量瀏覽器 | 快、省記憶體（**廠商自己的基準**，未獨立驗證） | beta、AGPL；人員頁有 JS 局部注入，相容性未證實 | 暫不測 |
| H PDF | pdfplumber（現有）、Docling、MarkItDown | 一份部落格基準中 pdfplumber 表格 TEDS 最高；Docling／MarkItDown 為 MIT | 非中文專屬基準；Docling OCR 對中文未說明 | 先維持 pdfplumber，新表單解析失敗再比 |
| I MCP 實驗 | 同一抓取功能做成程式內工具與自寫 MCP 伺服器 | 直接量協定開銷與 Gemma 呼叫成功率 | 要寫小伺服器 | P9 |
| J 代理式導覽 | Playwright MCP、Browser Use | 研究對照 | LLM 在迴圈中；穩定度低 | 獨立研究 |

**選擇準則（B 是否取代 A）**：在同一固定 URL 集上，B 在「JS 人員頁成功率、12 頁並行延遲、程式碼量與維護」勝出，且**不傷害格式相容性**（表單編號正規式命中、markdown 連結保留）才採用。每個組合**單次通過**小測試（D15），不求統計平均；評分卡欄位：成功率、欄位完整度（人名與分機召回）、格式相容、延遲、記憶體、維運成本、授權。

**未列入第一批**：Scrapy／Crawlee（適合批次重爬，屬被延後的更新管線）；Tavily／Exa／Brave（開放網路搜尋，對封閉語料用處小；資料出校）；ScrapeGraphAI／Apify MCP（主要連到各自雲端 API）；Stagehand（支援的模型不含已確認的 Ollama）。

### 5.18 MCP 的分工

MCP 只是工具的打包與傳輸方式，不決定穩定度。分工準則是**誰做決定**：

| 工作 | 做法 |
|---|---|
| 已知網址的現場確認、條件式 GET、雜湊比對、PDF 下載 | 程式碼（抓取器） |
| 表單編號擷取、辦公室判斷 | 現有函式（程式＋函式內的 LLM judge） |
| 列表頁項目與日期 | 確定性規則優先；抽不出才用 LLM |
| 探索式導覽（下一步點哪個連結） | LLM 在迴圈中，用既有 `get_page`／`extract_links` |
| 瀏覽器渲染池 | 獨立服務（Crawl4AI Docker 或 Browserless），這裡走 REST 或 MCP 邊界最有價值（隔離崩潰） |
| 新頁面發現的補充 | SearXNG（選配；新鮮度取決於上游引擎的索引，不能當保證） |

**MCP 的代價**：多一個行程、序列化與延遲、工具描述佔 token、工具越多 Gemma 越難選、SDK 版本漂移（官方 Fetch MCP 提到 SDK 2.0 移植中，已查證）。

**實驗 I（P9）**：同一抓取功能做成程式內 `@tool` 與自寫小型 MCP 伺服器兩版，比較延遲開銷、失敗率與 Gemma 呼叫成功率——直接量，不爭論。`langchain-mcp-adapters` 的相容性待驗證。

### 5.19 驗收與測試策略（用量有限）

- **驗收只用「休學」問題**，每階段端到端**最多跑一次**；「10/14 哪些處室有更新」在 P7 之後跑一次看結果，有答案再討論。
- **盡量讓測試不需要 LLM**：抓取、比對、日期解析、列表解析、速率限制、標記解析，都用**固定測試資料（fixture）**——第一次現場抓取時把回應存起來（`experiments/live_fixtures/`），之後離線重播。只有端到端那一次才用到模型。
- **固定測試資料注入**：把存下來的休學頁／表單改造成「表單變兩張」「站點變 12 個」的版本，餵給抓取器，在節點層級（不呼叫 LLM）驗證替換與傳遞；`on` 模式端到端最多再跑一次看答案如何改變。這解決了「官網現在沒變，如何證明替換有效」。
- eval 兩種模式：**快照鎖定**（`LIVE_FETCH=off`，沿用現有 criteria 與標準答案，可重現）與**即時**（差異由人工判斷哪邊才對，不直接用現有 criteria 判定，因為標準答案是從快照建的）。

---

## 6. 原型階梯（先有小原型，再逐步加上去）

每階段都有：範圍、驗收、停損點。**驗收皆為單次**（D15）。

### P0　探查與前置（不改行為）
- 範圍（三步）：
  1. **程式碼（無網路）**：`today` 注入——`rag/live/clock.py`、`AgentState.today`、`initial_state()` 填入；沒有節點讀它，行為不變。**（2026-10-14 已完成並離線驗證：圖可編譯、`initial_state` 帶出 `today`。）**
  2. **探查（httpx，約 45～70 個請求，上限 90）**：`experiments/live_spikes/p0_probe.py`。預設 dry-run，加 `--run` 才送；每個主機間隔 ≥ 1 秒、逾時 60 秒、TLS 驗證開、不跟隨轉址、只允許清單內的 7 個主機。內容：`robots.txt`、sitemap（含對 `www` sitemap 取樣檢查 404 原因）、HEAD 的 ETag／Last-Modified、軟 404、DNS（共用 IP）。輸出只寫 `experiments/live_spikes/_out/`。**（已於 2026-10-14 16:42 執行，49 個請求，結果見 §11。）**
  3. **固定測試資料（Playwright＋httpx，約 16～25 個請求）**：**（2026-10-14 已完成：`capture_chain.py`，httpx 16 個請求＋Chromium 9 頁，存於 `experiments/live_fixtures/chain_xiuxue_2026-10-14/`（gitignored）；結果見 §11.7。P0 全部完成。）**
- **不跑基線端到端**（使用者決定，2026-10-14）：品質基線已知（`off` 模式歷次約 24～26／26）；新增延遲由抓取器自己的計時器直接量測（現場階段耗時），不靠兩次端到端 LLM 執行相減——雲端 LLM 的耗時與取樣雜訊遠大於要量的差距，相減不可靠，也多耗用量。
- 驗收：一份探查報告（§7 前幾列的答案）＋固定測試資料存檔。
- 停損：若連基本現場抓取都被擋（驗證頁、4xx、429），停下來重新評估，不往下做。

### P1　抓取器核心＋比對＋獨立檢查腳本（對 `get_page`，尚不啟用）
- 範圍：`config`、`fetcher`、`compare`（含 `normalize`）、`cache`、`ratelimit`、`allowlist`；`experiments/live_spikes/check_chain.py`（休學鏈約 16 個 URL，同時取快照與現場、比對、出報表）；`get_page` 掛鉤先寫好但行為仍是 `off`。
- 驗收：fixture 單元測試全過（無 LLM）；檢查腳本**跑一次**：每個 URL 的 相同／不同／失敗 與耗時、差異摘要；**全程不呼叫 LLM**。
- 停損：若「沒有內容變動的頁面」相同率過低（正規化無法壓住假差異），先修正規化再往下。
- **進度（2026-10-14）**：程式與離線測試完成——`rag/live/{config,allowlist,compare,ratelimit,cache,fetcher,resolve,hook}.py`；`get_page_tool` 已掛 `apply_page()`（`LIVE_FETCH=off` 回傳同一個物件，行為不變）；`experiments/live_spikes/test_live_p1.py` 38 項全過（MockTransport＋fixture，無網路、無 LLM）。`check_chain.py --offline` 以 Chromium 抓下的 fixture 對 8/25 索引比對：休學頁相同；9 個人員頁中 3 個相同、6 個不同（教務長室、註冊組表頭改版、住宿輔導組與身心健康中心的職務代理人換人、原資中心業務敘述、國合處信箱），其餘皆為真實內容變動。測試中另發現 cashier 頁尾的 `瀏覽人次: N 人` 計數器（已加入 `VOLATILE_*`）。實作備註：抽取器在內容為空時會回傳網址最後一段當標題，fetcher 已把這種情況判為 `empty`，不當成內容。**`check_chain.py --run` 已執行一次（2026-10-14 18:56，10 個 httpx GET，無 429／5xx／重試，總耗時 30.3 秒，其中 osa 4 頁因 10 秒間隔佔 30 秒）**：
  - 單頁耗時（不含 osa 排隊）：aca 2.2～2.7 秒、cashier 2.6 秒（`verify=False`）、www.lib 0.4 秒、oic 0.5 秒；osa 每頁的 10／20／30 秒是限速器排隊，不是伺服器慢。
  - **靜態 httpx 抓到的人員頁與 Chromium 渲染結果相同的有 8／10**（含 osa 4 頁、aca 3 頁、cashier）：差異清單與離線重播逐項一致。→ 這些頁面人員資料不需要 Chromium，推翻 §5.9 的「靜態抓不到」假設（只對這 8 頁成立；其他網域未驗證）。
  - 例外 2 頁：**oic 國合處**靜態只得 37 字（快照 4,956 字），內容是 JS 渲染；**www.lib** 的差異是 `<noscript>` 文字與空的 `瀏覽數:`（計數器由 JS 填入），皆為靜態與渲染版的人工差異。
  - 因此新增兩項防護：①`resolve` 新狀態 `live_incomplete`——現場正規化長度 < 快照的 50%（`INCOMPLETE_RATIO`，估計值）就視為未渲染的 JS 頁，保留快照並標記需要 Chromium，**避免用殘缺的現場頁取代完整快照**；②`VOLATILE` 加入 noscript 行與無數字的計數器標籤。這兩項只以單元測試（用實測字串）驗證，沒有為此重送請求。
  - 6 個「不同」（註冊組、教務長室、住宿輔導組、生僑組、原資中心、身心健康中心）靜態與渲染一致，且內容是人員／職務／業務敘述的實質變動。

### P2　`on` 模式（頁面）＋資料狀態標記＋固定測試資料注入
- 範圍：啟用 `LIVE_FETCH=on`；標記行與 `ledger`；`get_page_tool` header；`self_eval` Stage 1 新檢查；`_detect_offices` 內容雜湊快取；allowlist 與內容隔離。
- 驗收：注入測試（節點層、無 LLM）；休學**一次** `on` 端到端（真實現場）：以既有 criteria 分數（歷次 `off` 約 24～26／26）當參照，**不另外跑一次 `off`**；人工檢查資料狀態段與「現場確認」的內容；若答案內容與快照版不同，人工判斷哪邊才對。
- 停損：現場失敗率過高 → 檢討重試／斷路參數。

- **P2 進度（2026-10-14）**：程式與離線測試完成（`experiments/live_spikes/test_live_p2.py`，連同 P1 共 64 項全過，無網路、無 LLM）。內容：`rag/live/ledger.py`（標記行 `[live:src status=… checked=… snap=… tls=… url=…]`，只解析 ToolMessage 標頭、頁面文字中的 `[live:src` 被中和，防偽造）；`hook.apply_page(url, page)`（`off` 回傳同一物件，`on` 抓取＋比對＋依狀態選文字）；`get_page_tool` 標頭帶標記（不影響 `[偵測到表單編號]` 路由標記）；`synthesis_node` 在 LLM 答案後由**程式**附上 `【資料狀態】` 段（`off` 時為空字串，答案逐位元相同）；`server.py` 把這段當最後一個 SSE chunk 送出；Stage 1 新增 `_check_data_state_disclosure`——有 `snapshot_fallback`／`live_incomplete` 而答案沒有 `【資料狀態】` 時才失敗，且**每題最多觸發一次**（提醒訊息帶「資料狀態揭露」標籤，再次檢查時看到就不再失敗），Stage 1 失敗時不呼叫 LLM。與計畫的差異：①`_detect_offices` 內容雜湊快取**暫不做**——`live_same` 使用快照文字，文字與 `off` 完全相同，沒有需要快取的重複呼叫；快取還會把一次 LLM 抽樣結果（先前記錄該步驟短輸入失敗率高）固定下來，使 self_eval 重試失去重新取樣的機會。②頁尾明確寫出「表單內容、承辦人與分機尚未現場確認」（`UNCHECKED_KINDS`），避免只涵蓋頁面卻讓使用者以為整條鏈都已確認；P3、P4 落地時各移除一項。**休學 `LIVE_FETCH=on` 端到端已跑一次（2026-10-14 22:24，`agentic_rag.py "如何辦理休學" --stream`，共 3 輪、約 73 秒）**：分數 **24/26**（`nine_stamps` 1/2、`contact_info` 1/2，落在歷次 24～26 的範圍內）；只有 1 個現場請求（aca 休學頁，`live_same`，與快照一致），快取有 1 筆；`【資料狀態】`段與「表單內容、承辦人與分機尚未現場確認」一句皆正確出現；self_eval 一次通過。兩項扣分都是 eval 的字面關鍵字：`nine_stamps` 要字面「住宿組」而答案寫「住宿輔導組」（其餘 8 個關鍵字都在）；`contact_info` 要 62123／63279 等，答案寫出納 62120、註冊組 63273／63281（出納兩個分機是語料已知的跨頁不一致）。本次**沒有記錄現場階段耗時**（成功路徑原本不寫日誌），已補一行 INFO 日誌，之後的執行才有數字；估計值仍是 check_chain 量到的 aca 單頁約 2.2 秒。

### P3　表單現場取得（moltke）＋PDF 暫存
- 範圍：`forms.py`；`get_form` 掛鉤；停用偵測；沒有編號的文件連結偵測；PDF 暫存與雜湊。
- 驗收：fixture 測試（viewdetail 頁、小 PDF、停用頁）；注入「表單變兩張」節點層通過；一次端到端。
- 停損：若 moltke 兩步取得不穩，表單維持快照＋標示。

- **P3 進度（2026-10-15）**：程式與離線測試完成（`experiments/live_spikes/test_live_p3.py` 18 項，連同 P1／P2 共 82 項，無網路、無 LLM）。內容：`rag/live/forms.py`（`fetch_form`：5 請求鏈，**每張表單一個獨立 client／cookie jar**；停用偵測；PDF 以 `df?<token>` 取得、驗 `%PDF`、存 `rag/live/_cache/pdf/<hash>.pdf`、用同一支 `extract_pdf`；圖片型 PDF 不 OCR → 失敗退回快照；結果存旁路快取 kind=form）；`Fetcher` 新增 `new_session()`、`client=`、`raw=True`（回傳原始位元組給呼叫端解析）；`hook.apply_form`（同頁面規則：相同用快照、不同用現場、失敗退回快照＋揭露、停用 → 文字清空並標 `discontinued`、快照沒有的新表單 → `live_new`）；`get_form_tool` 標頭帶標記；帳本新增 `kind=form`、`discontinued`，並能從 `resource_node` 組合訊息的 `get_form` 標頭解析標記（偽造的標記無法進入：內文先經 `sanitize`）；`UNCHECKED_KINDS` 移除「表單內容」。fake moltke 伺服器**真的以 cookie 決定回哪張表單**（最後一個 `viewFormDetail.jsp` 網址不帶編號）：三張表單平行抓各自正確；對照組（共用 cookie jar）確實取錯，且把實作改成共用 client 時該測試會失敗（已用變異測試確認）。節點層注入：頁面一次列出「快照已知＋快照沒有」兩張表單，`resource_node` 兩張都現場取得、標記為 `live_same`／`live_new`。moltke 單網域並行調為 2（獨立 cookie jar 之下安全；原為保守的 1）。待辦：休學 `on` 端到端**一次**（約 +15 個 moltke 請求，需核准）；「同編號換新版時 `df?<token>` 是否變動」仍未驗證（需要現場剛好有新版，離線無法測）。

### P4　人員頁現場渲染（組合 A）
- 範圍：`contacts.py`；Playwright 一個瀏覽器多 context；職務解析；`dynamic_contacts_for_office` 掛鉤；索引後備。
- 驗收：休學約 10 個處室**一次**渲染的耗時與完整度（對照索引，差異人工確認）。
- 停損：若渲染耗時不可接受 → 評估預熱或 B／C。

### P5　預測性預抓＋共用快取調優
- 範圍：`prefetch.py`。驗收：與無預抓的單次耗時比較。停損：效益不明顯就不啟用。

### P6　挑戰者 B（Crawl4AI）轉接器＋評分卡
- 範圍：安裝（§9）、`adapters/crawl4ai.py`、`experiments/live_spikes/` 的共同測試框架；固定 URL 集單次跑完。驗收：評分卡填完，依 §5.17 準則決定是否採用。停損：B 在格式相容上不及格就放棄。

### P7　`recent_node`
- 範圍：`timeintent`、`dates`、`registry.json`、`recent.py`、答案形狀；先 2～3 個網域，再擴大；擴大前重新評估 D11（User-Agent／知會計中）。
- 驗收：fixture 測試（日期解析、列表解析、分頁與置頂）；「10/14 哪些處室有更新」**跑一次看結果**，有答案再討論。

### P8　Sources 面板與答案格式
- 範圍：`sources` SSE 事件（依處室分組，「查閱 N、引用 M」）；前端改動在另一個 repo（`CourseLangChain-frontend`，本計畫未讀）。

### P9　MCP 實驗 I、代理式導覽 J
- 範圍：見 §5.18；僅研究用途，不進產品路徑。

### P10　上線前置（另案）
- session 驗證與持久化 checkpointer、共用限速（多行程）、降級、LLM 速率與成本評估、更新管線的觸發條件評估（§8）。

---

## 7. 驗證項目（列入各階段）

| 項目 | 階段 |
|---|---|
| 各站 `robots.txt` 是否存在、有無 `Crawl-delay`（`www` 已由使用者查看：`Allow: /`；其餘 `aca`、`osa`、`cashier`、`lib`、`oic`、`moltke` 待查，可由使用者在瀏覽器直接開，或 P0 各送一次 GET） | P0 |
| 不同子網域是否共用同一台伺服器或防護設備（決定全域併發要看整體速率，還是單網域速率） | P0 |
| 各站 `ETag`／`Last-Modified`、sitemap、RSS（sitemap 要先讀 `robots.txt` 的 `Sitemap:` 行，再試 `/sitemap.xml`、`/sitemap_index.xml`；原始爬蟲只做後者；是否能用 `lastmod` 偵測編輯也一併看） | P0 |
| 同一頁、同一抽取器、現場 vs 快照在無變動時的相同率；點擊數之外的動態欄位 | P1 |
| 伺服器端或中間代理對長時間 SSE 的行為（前端無逾時，已由使用者確認） | P2 |
| moltke `goFile` token 是否隨版本改變；`viewdetail` 對所有編號是否通用；兩步取得耗時 | P3 |
| Playwright 渲染 10～12 頁人員頁耗時；固定 2 秒等待是否合適或改等待選擇器 | P4 |
| 休學一次查詢的實際請求數（對照 §4.2 估計） | P1～P4 |
| Crawl4AI：能否取得原始 HTML、`/pdf` 端點用途、是否「支援圖片」、對繁中頁面表現 | P6 |
| Docling／MarkItDown 對中文 PDF 表格的表現（僅在 pdfplumber 失敗時） | P3／P6 |
| `langchain-mcp-adapters` 與現有 LangGraph／langchain 版本相容性 | P9 |
| Lightpanda、Firecrawl 自架的資源需求與相容性 | 候補，不排程 |
| 列表頁是否靠 JS 渲染、日期是否可解析的比例 | P7 |

**sitemap 間接推測（2026-10-14，讀本地 `map.json`，尚未驗證）**：原始爬蟲把 sitemap 找到的網址與種子一起以 `depth=0、parent=None` 放入佇列（`NCCU-Crawler/crawler.py` 的 `bfs` 與 `discover_sitemap` 呼叫處）。使用者表示從未使用 `--retry-failed`，所以不考慮重試造成的 depth-0 膨脹（`/crawl-subdomain` 的流程含 retry-failed 階段，若某些子網域用該流程爬則可能例外）。231 個子網域的結果：
- 171 個 depth-0 ≤ 2 筆：推測沒有可用的 sitemap，包含 `aca`、`osa`、`oic`、`www.lib`。
- 57 個 depth-0 > 20 筆：22 個多數網址仍可抓到（如 `learning` 1,929 筆全部成功，推測 sitemap 準確）；27 個多數是 404（如 `www` 238／240、`dean` 111／121、`cashier` 36／37，推測 sitemap 過期，**或爬蟲的網址正規化改壞了網址——待驗證**，例如 `www` 出現 `/p/p/404-1000-….php` 這種重複路徑）；8 個混合。
- 結論（暫定）：核心行政單位不能依賴 sitemap；`recent_node` 以公告列表頁為主，sitemap 僅作少數主機的補充。P0 要直接看 `www` 的 sitemap 以分辨 404 的原因。

---

## 8. 風險與未決事項

| 項目 | 狀態 |
|---|---|
| **官網本身過時或不一致** | 不可消除；以揭露來源與時間因應 |
| **被擋 IP** | 以 §5.5 限速降低（保守起步，全域併發 4）；User-Agent 沿用原始爬蟲的字串（D11）；不知會計中。**該 UA 只指向學校首頁，若 P7 擴大掃描後被擋，對方無法循 UA 聯絡到專案，也沒有事先通知可依**——屆時重新評估 |
| **現場內容的 prompt injection** | §5.15；P2 起做 |
| **比對假差異／假相同** | §5.2；P1 人工抽查 |
| **LLM 用量** | 現場功能本身不增加 LLM 次數；內容雜湊快取可減少；檢查腳本全部用確定性比對 |
| **多行程共用限速與快取** | 上線前置（P10） |
| **預抓增加對政大伺服器的請求** | 每題預算；先量基線再決定啟用 |
| **「更新」只算新增項目** | D7；編輯偵測待驗證各站訊號後再議 |
| **更新管線何時才需要** | 觸發條件：①量測顯示快照與現場差異大（核心處室有明顯比例的頁面已變）；②現場失敗率高到常退回舊快照；③要把監看擴大到 154 個子網域並維持列表頁新鮮；④準備大量上線需要新鮮的後備。可用檢查腳本與 `on` 模式的差異日誌當「髒頁清單」（記錄已發現變動的網址），作為日後重爬的待辦 |

---

## 9. 指令與安裝清單（**僅列出，尚未執行；需要安裝時請自行執行**）

### 9.1 分支

```bash
cd /mnt/d/NCCU_DATA/NCCU-AI-SYSTEM/nccu-academic-rag
git status                       # 確認目前在 main、沒有未預期的修改
git switch -c feature/live-fetch # 從 main 切出新分支（未追蹤檔案會一起帶過去，不受影響）
# 日後切回：git switch main
```

提交這份計畫（由你自己執行）：

```bash
git add docs/phase_j_live_fetch_plan.md
git commit -m "docs: add Phase J live-fetch plan"
```

### 9.2 Python 套件

目前 `requirements.txt` 已有：`httpx`、`beautifulsoup4`、`lxml`、`playwright`、`pdfplumber`（已查證），組合 A **不需要新安裝**。Playwright 的瀏覽器若尚未安裝：

```bash
playwright install chromium
```

之後才可能需要（**全部尚未安裝；指令依官方 README，版本請自行確認**）：

```bash
# 組合 B：Crawl4AI（P6）
pip install -U crawl4ai
crawl4ai-setup

# 組合 C：Crawl4AI Docker 服務（P6 之後）
docker pull unclecode/crawl4ai:latest

# PDF 對照（僅在 pdfplumber 失敗時）
pip install docling
pip install markitdown

# 選配：列表頁日期與 sitemap／RSS 工具
pip install trafilatura

# MCP 實驗 I（P9）
pip install mcp
```

---

## 10. 預期結果

### 10.1 休學問題（單次驗收，不求統計）

| 面向 | 現況 | 預期（`on`） |
|---|---|---|
| 資料時間 | 不揭露（實為 2026-08） | 每個來源標示「現場確認／與快照一致／快照後備」與時間 |
| 流程變動（表單、站點） | 無感，仍答舊的 | 沿依賴鏈自動反映（以固定測試資料注入驗證） |
| 人員 | 8 月名單 | 現場讀取各處室現任職務；讀不到就明說 |
| 連結 | LLM 在答案最後自己打 | 由程式依標記產生，來源一定來自本次實際讀取 |
| 延遲 | 無網路請求 | 約多 8～12 秒（**估計**；全域併發 4；P0／P4 實測；整題只警告不中止） |
| LLM 呼叫次數 | 約 6～12 次 | 大致相同（內容雜湊快取可能略減） |
| 可重現性 | 完全可重現 | `off` 仍完全可重現；`on` 隨官網變動，eval 需雙模式 |

### 10.2 「10/14 哪些處室有更新」（P7 後跑一次）

預期得到：依處室分組的新增項目清單、涵蓋統計、無法檢查的處室名單，且**不把未檢查的處室寫成「沒有更新」**。成功與否先看「能不能跑起來、涵蓋多少、日期解析準不準」，答案品質有結果後再討論。

### 10.3 研究面

- 一組可引用的數據：快照漂移率、現場失敗率、各網域延遲、比對假差異率。
- 「現場確認＋替換」不增加 Gemma 的工具選擇點，可作為「在不犧牲小模型穩定度下做到即時資訊」的案例。
- MCP 與程式內工具的對照（實驗 I）、組合 A 與 B 的評分卡。

---

## 11. P0 探查結果（2026-10-14 16:42，49 個請求；原始資料在 `experiments/live_spikes/_out/`，gitignored）

方法：`p0_probe.py --run`（循序、同主機間隔 ≥ 1 秒、TLS 驗證開、不跟隨轉址、User-Agent 選項 A）。以下全部是本次實測（已查證），除非標示（推測）。

### 11.1 逐主機

| 主機 | robots.txt | sitemap | 其他 |
|---|---|---|---|
| `www` | 200：`Allow: /` | `/sitemap.xml` urlset，**8,936 筆**；`lastmod` 2018-08-31～2026-10-14T16:42:33（8,932 個不同值，不是「產生時間」）；取樣 10 筆**全 200**；`/p/p/` 網址 0 筆 | HEAD `/` 回 **403**（GET 其他頁正常）；不存在路徑回 404 |
| `aca` | 200（Joomla）：15 條 `Disallow`、無 `Crawl-delay`、**有 `Sitemap:` 行**；註解寫「Updated: 2026-09 - added Sitemap」 | `/sitemap.xml` urlset，**5,786 筆**；`lastmod` 2006-01-17～2026-09-16，**只有 8 個不同值**；取樣 5 筆全 200 | 頁面 `Last-Modified` = 請求當下、`Cache-Control: no-store`、無 ETag；HEAD `/zh/最新消息` 回 **500**；不存在路徑 301 → 加語言前綴 |
| `osa` | 200（Joomla 預設檔）：**121 條 `Disallow`、`Crawl-delay: 10`**、無 `Sitemap:` 行 | `/sitemap.xml`、`/sitemap_index.xml` 都 **301 → `/tw/sitemap.xml`、`/tw/sitemap_index.xml`**（未跟隨，內容未知） | `Last-Modified` = 當下、`no-store`、無 ETag；不存在路徑 301 → 加 `/tw/` |
| `cashier` | **TLS 驗證失敗**：`unable to get local issuer certificate` | 同左 | 所有請求都連線失敗（含 HEAD） |
| `www.lib` | 200：`Allow: /` | 無（404） | HEAD `/` 回 **403**；不存在路徑 404 |
| `oic` | 200 但是 **HTML**（軟 404，等於沒有 robots） | `/sitemap.xml`、`/sitemap_index.xml` 回 200 但不是 XML（軟 404） | IIS／ASP.NET；不存在路徑 **302 → `/ErrorPages/404.html?…`**；HEAD `/` 200、無 Last-Modified、`Cache-Control: private` |
| `moltke` | 404（無） | 無（404） | HEAD viewdetail → 302 `login.formservice?viewdetail=…`（既有腳本以 `follow_redirects=True` 處理） |

- 7 個主機 IP 各不相同（`www` 140.119.168.10、`aca` 140.119.9.79、`osa` 140.119.9.74、`oic` 140.119.9.100、`cashier` 140.119.24.156、`www.lib` 140.119.127.210、`moltke` 140.119.229.210）；`aca`／`osa`／`oic` 在同一個 /24 網段，是否共用防護設備未知。
- 200 回應耗時多在 8～1,200 ms（靜態與動態頁差很多）。

### 11.2 對計畫的影響

1. **`www` 的 sitemap 是真的、很新、而且準**（取樣全 200、`lastmod` 逐頁不同）。先前「`www` 238／240 筆 404 是 sitemap 過期」的推測**不成立**；更可能是舊爬蟲的 URL 處理問題，或當時的 sitemap 版本不同（待驗證）。**語料覆蓋缺口警訊**：sitemap 列 8,936 頁，而 `output/www/map.json` 只有 1,073 筆（含失敗）。需量化重疊（P0b）。
2. **`aca` 的 sitemap 是 2026-09 才新增的**（robots 註解），所以 8 月的爬取沒有它，與 `depth=0` 只有 1 筆吻合。但它的 `lastmod` 只有 8 種值 → 粒度很粗，**不能用來偵測個別頁面的編輯**。
3. **`ETag`／`Last-Modified` 在 `aca`／`osa` 不可用**：`Last-Modified` 是請求當下的時間（動態產生）、`Cache-Control: no-store`、沒有 ETag。**條件式 GET 在這兩台無法使用，只能用內容雜湊比對**（§5.2 本來就以雜湊為主，「條件式驗證」只是可用時的優化，在這兩台不成立）。
4. **HEAD 不可靠**：`www`、`www.lib` 的 HEAD `/` 回 403；`aca` 的 `/zh/最新消息` 回 500。現場抓取一律用 GET；列表頁網址不能用猜的，要從 `map.json`／登錄表取得（`/zh/最新消息` 這個根網址不是可用的頁面）。
5. **`osa` 要求 `Crawl-delay: 10`（秒），並有 121 條 `Disallow`。** 計畫 §5.5 寫「有 `Crawl-delay` 就遵守」；若照做，休學鏈在 `osa` 的 4 個處室頁至少要 30～40 秒。**待決 A。**
6. **`cashier` 的 TLS 憑證鏈不完整**（缺中繼憑證），Python 預設信任庫無法驗證；原始爬蟲因 `verify=False` 才抓得到。出納組在休學鏈上，所以必須處理。**待決 B。**
7. **軟 404 有三種形式**：`oic` 對不存在的檔案回 200 HTML、對不存在路徑 302 到錯誤頁；`aca`／`osa` 對不存在路徑 301 加語言前綴（最終是否 404 未跟隨）。robots／sitemap 的檢查必須判斷內容格式，不能只看狀態碼。
8. `moltke` 沒有 robots／sitemap；表單頁會 302 到 `login.formservice`，既有腳本以跟隨轉址處理。

### 11.3 待決與後續

- **決定 A（使用者，2026-10-14）：先完全遵守 `robots.txt` 與 `Crawl-delay`**（`osa` 同主機請求間隔 10 秒），之後若覺得可以優化再更正。理由：遵守成本低，抓取可與 LLM 的耗時重疊（§5.10 預測性預抓：LLM 還在改寫、規劃時先在背景慢慢抓），再加上 TTL 60 分鐘，只有第一次查詢付出代價。`HOST_INTERVAL = {"osa.nccu.edu.tw": 10.0}` 已寫進 `p0_probe.py`，正式抓取器的設定檔沿用。已否決的選項：(b) `osa` 人員頁改走快照＋排程重爬；(c) 縮短間隔承擔風險（不建議）。
- **決定 B（使用者，2026-10-14）：對 `cashier` 的 httpx 路徑使用 `verify=False`**，沿用原始爬蟲的做法（原始資料即是如此取得）；範圍限縮為明確的主機清單（§5.15）。已否決：取得 TWCA 的 `Cyber_SSL_2023.crt` 加入專用信任庫（因此 **P0c 取消**，不需要對 TWCA 發請求）。Chromium 路徑（人員頁）仍驗證。
- **P0b（小量請求，≤ 10，需使用者核准才送）**：①再抓 `www`、`aca` 的 sitemap 各 1 次，量化與語料的重疊與 `lastmod` 分佈；②`osa` 的 `/tw/sitemap.xml`，以及 `osa`、`aca` 的 robots 完整內容各 1 次（核對我們要抓的路徑是否被 `Disallow`）；③`www`、`www.lib` 的 `GET /`（確認 403 是否只針對 HEAD）；④`aca` 的 `GET /zh/最新消息`；⑤`cashier` 的憑證鏈檢查（1 次 TLS 握手，不送 HTTP）。

### 11.4 三家 AI 公司對 robots.txt、Crawl-delay、憑證的公開說法（2026-10-14 查官方文件；供日後優化「遵守」政策時參考）

| | robots.txt | Crawl-delay | 憑證 |
|---|---|---|---|
| Anthropic（ClaudeBot、Claude-User、Claude-SearchBot） | 官方寫「遵守 robots.txt 的標準指令」 | **支援這個非標準指令**（範例 `ClaudeBot` 設 `Crawl-delay: 1`），但未說明 Claude-User 是否同樣遵守 | 未說明 |
| OpenAI（GPTBot、OAI-SearchBot、ChatGPT-User） | 搜尋與訓練以 robots.txt 控制；**ChatGPT-User 寫「因為這些動作由使用者發起，robots.txt 規則可能不適用」** | 未說明 | 未說明 |
| Google（一般爬蟲；使用者觸發的抓取器含 Google-GeminiNotebook、Google-Agent） | 一般爬蟲自動爬取時一律遵守；**使用者觸發的抓取器「通常忽略 robots.txt」**（理由：抓取是使用者要求的） | 所讀頁面未提 | 未說明 |

- 三家都區分「自動爬取」與「使用者要求的抓取」，後者可能不受 robots.txt 約束；三家的爬蟲 UA 含自己的網址並公布 IP 清單。
- 我們的現場抓取也是學生提問觸發，理論上可套用同樣的論點；**但本計畫選擇遵守**（決定 A）：這是學校自己的伺服器、成本低，且 `osa` 的 10 秒本質上是在保護它的伺服器。因此我們比三家公開的做法更保守，這是刻意的。
- 憑證：三家都沒有公開說明；一般而言 OpenSSL 類客戶端（Python、curl）遇到缺中繼憑證的伺服器會失敗，瀏覽器則會自己補抓。
- `cashier` 的 robots.txt（使用者貼出，我們的 httpx 無法驗證其 TLS 鏈所以未自行抓取）：對所有機器人禁止 `/intra`、`/intranet` 開頭的路徑；「Example 1/2/3」是註解（疑為抄自 Google 文件的範例）。我們要抓的 `PageStaffing?fid=7994` 不受影響；`cashier` 語料 156 筆網址中沒有任何一筆在 `/intra*` 底下（已離線驗證）。

### 11.5 P0b 探查結果（2026-10-14，6 個 GET＋1 次 TLS 握手＋1 次 Chromium 載入 `cashier` 人員頁；`osa` 請求間隔 10 秒；原始資料 `experiments/live_spikes/_out/p0b_raw.json`）

| 項目 | 結果 |
|---|---|
| **`www`：sitemap 與語料幾乎沒有重疊** | sitemap 8,937 筆，其中 8,907 筆是 `/p/404-1000-N.php`（文章／內容頁）；語料裡 `www` 可讀的 831 頁主要是 `406-…,rN` 系列文章頁（367 筆）、`426` 人員頁（34 筆）等其他系列（先前我誤稱 `406` 為列表頁，實際查看存檔 HTML 後確認它們是文章頁），**只有 2 筆 `404` 內容頁**。以完整網址比對只重疊 4 個，但那是因為舊爬蟲抓到的是同一批文章的另一種網址形式（`406-…,rN`）；**以文章編號比對**：sitemap 8,907 篇 `404` 文章中，語料以任一系列涵蓋的只有 210 篇，缺 **8,697 篇（97.6%）**。**也就是說 agent 目前讀不到 `www` 的文章內容**（**真正的原因見 §11.6**；先前「ajax 載入列表」與「孤兒頁」兩個假設，都已被查證結果修正）。這與是否做現場抓取無關，是語料本身的缺口；現場抓取的「快照沒有的網址也抓」（`live_new`）正好補上 |
| **`www` sitemap 可當「今日新增或修改」的來源** | `lastmod` 逐頁不同（8,932 個不同值）：探查當下有 **14 筆在 10/14、7 筆在 10/13、24 筆在 10/12**；最近 1 天內 14 筆、7 天內 67 筆、30 天內 155 筆、90 天內 217 筆，其餘（8,484 筆）更早；快照（2026-08-05）之後修改過的有 381 筆（約 4.3%，前提是 `lastmod` 反映真實修改，待抽查）。可作為 `recent_node` 對 `www` 的主要來源之一（另加列表頁）。尚待驗證：`lastmod` 是否等於頁面上的發布日期（抽 5 頁比對） |
| **`aca`：語料覆蓋 sitemap 99.2%** | sitemap 5,786 筆，其中 5,737 筆已在可讀語料中（缺 49 筆，多為 `/db/upload/` 的 PDF）。但 **`lastmod` 不可用於偵測編輯**：只有 1,558 筆有 `lastmod`、僅 8 種不同的值（批次戳記）；「快照後修改 1,446 筆」是批次日期，**不是** 1,446 筆真實編輯 |
| **`osa`：沒有 sitemap** | `/tw/sitemap.xml`（P0 的 301 目標）回 404。先前的 301 只是語言前綴轉址 |
| **robots.txt 對休學鏈頁面的限制** | `aca` 完整 robots 對休學鏈用到的 8 個頁面**全部允許**；`osa` 對 12 個頁面**全部允許**；`cashier` 人員頁依使用者貼出的規則（只禁 `/intra*`）允許 |
| **`www.lib` 的 403 只針對 HEAD／根網址** | 內容頁 `/p/404-1000-312.php?Lang=zh-tw` 的 GET 回 200（58 KB、298 ms）。再次確認：現場抓取一律用 GET |
| **`cashier` 的 TLS 問題已確診** | 伺服器只送 2 張憑證：葉憑證（`*.nccu.edu.tw`，由 `TWCA SSL Certification Authority` 這個 Sub-CA 簽發）＋ `TWCA CYBER Root CA`（由 `TWCA Global Root CA` 簽發）；**缺少簽發葉憑證的中繼憑證（TWCA SSL Sub-CA）**，驗證碼 21。葉憑證的 AIA 指向 `http://sslserver.twca.com.tw/cacert/Cyber_SSL_2023.crt`。其他主機（`aca`、`osa`、`www` 等）驗證通過，所以是 `cashier` 的伺服器設定問題，不是整個 `*.nccu.edu.tw` |
| **`cashier` 人員頁用 Chromium 載入** | 成功（200，約 4.6 秒含固定 2 秒等待，Chromium 151，無失敗的子請求，非 Cloudflare 驗證頁）；抽出 2,734 字；**頁面上 12 個 5 位數分機與索引中的快照完全相同**（無新增、無消失）——第一個人員漂移實測：出納組自 2026-08-25 快照以來，分機沒有變動 |

**對計畫的影響**
1. **「快照沒有的網址也現場抓取」（`live_new`）不是加分項，是必要功能**：`www` 有約 8.9k 個內容頁完全不在語料裡。
2. `recent_node` 的來源要依主機區分：`www` 用 sitemap `lastmod`（待抽查）＋列表頁；`aca` 只能用列表頁（`lastmod` 是批次戳記）；`osa` 沒有 sitemap，只能用列表頁。
3. **決定 B（已定，見 §11.3）**：`cashier` 的 httpx 路徑用 `verify=False`（明確主機清單）；休學鏈在 `cashier` 只用到人員頁，本來就走 Chromium（驗證仍開著），所以**不被擋住**。P0c（對 TWCA 發請求取憑證）取消。
4. 抽取器輸出的連結格式有疑似異常：`[:::](http:cashier.nccu.edu.tw/PageStaffing?fid=7994#accesskey-l)`（缺 `//`）；快照與現場兩邊一致，所以不影響比對，但 P1 的正規化與連結解析要留意。
5. **現場抓取只能補「已知網址」，補不了「依主題找未知頁面」**：`www` 約 8.9k 個內容頁不在語料也不在 FTS5，agent 無法用主題搜尋到它們；`live_new` 只有在知道網址時（來自 sitemap、列表頁、`lastmod` 或使用者給的連結）才有用。`recent_node`（問「今天有什麼」）可行；「某場講座在哪裡舉辦」這類主題式提問，在這些頁面上仍會落空。日後的選項（**不是現在的決定**）：對 `www` 依新 sitemap 做一次定向爬取（約 8.9k 頁，以每頁約 1 秒估計約 2.5 小時）；或找 `www` 的站內搜尋端點；或從 ajax 模組取得列表。其他使用同一個 CMS 的主機（例如 `cashier`、`dean`）可能有同樣的缺口，未查證。

### 11.6 `www` 語料缺口的真正原因（2026-10-14 查證；P0c 載入 `www` 首頁一次＋本地資料）

**結論**：舊爬蟲抓不到這些文章，是因為 **`www` 列表頁的分頁寫法是爬蟲看不懂的新版**，所以只抓到每個列表的第 1 頁（最新的一批），第 2 頁以後的舊文章從未被發現。

| 證據 | 結果 |
|---|---|
| Chromium 載入 `www` 首頁（渲染後 951 個連結） | 指向 `/p/404-1000-N` 文章的連結**只有 1 篇**（`404-1000-23396`，sitemap `lastmod` 為 2026-07）；伺服器原始 HTML 也是 1 篇。**首頁只保留新資訊**（使用者的猜測成立），而且 JavaScript 並沒有往首頁加入大量文章連結——先前「`hajaxOpenUrl` 載入公告列表」的推測**被推翻**（那 19～20 個模組是選單等，不是文章列表） |
| 列表頁連到哪裡 | 首頁的「校園公告」連到 `/p/403-1000-206-1.php`，另有「更多招生公告」（`403-1000-125-1`）、「更多教師招募公告」（`403-1000-42-1`）、「更多徵才公告」（`403-1000-40-1`）等列表頁。舊爬蟲抓到的 `403` 列表頁連到的是 `406-1000-N,rM.php`（列表脈絡下的文章網址，352 個連結），**不是 `404-1000-N.php`**；兩者是同一批文章的兩種網址形式：語料中 304 個 `406` 頁的文章編號，有 203 個也出現在 sitemap 的 `404` 頁 |
| 列表頁有分頁，但爬蟲看不懂 | 存檔的「校園公告」列表頁（`403-1000-206.php`）有 7 頁，分頁由 jQuery 點擊事件處理（`ptpagelist.goPage(N)`，最後一頁 `goPage(7)`）。舊爬蟲的 `_extract_js_pagination()`（`NCCU-Crawler/crawler.py`）只認舊版寫法：`javascript:goPage(N)` 連結＋`location.href = "…" + page` 的網址範本。對這個頁面：範本正規式**沒有命中**、`javascript:goPage` 連結 **0 個** → 分頁完全沒被跟進 |
| 影響範圍（抽樣，每個子網域最多 100 個存檔 HTML，離線） | 使用新版分頁（`ptpagelist`）的子網域至少有 5 個：`www`、`www.lib`、`cc`、`dhl.lib`、`archive.lib`；使用舊版分頁（爬蟲看得懂）的有 84 個。抽樣有限，實際可能略多 |

**更正我先前的兩個說法**：①「`www` 與 sitemap 只重疊 3 頁」是網址形式不同造成的假象（見 §11.5 該列的修正）；②「首頁以 `hajaxOpenUrl` 載入文章列表」已被推翻（見上）。

**對計畫的影響**
1. **`recent_node` 對 `www` 可行，而且用 httpx 就夠**：每個列表的**第 1 頁是靜態 HTML**（舊爬蟲就是靠它抓到 `406` 文章），最新的項目都在這裡；加上 sitemap 的 `lastmod`（逐頁不同）做交叉。不需要 Chromium。
2. **舊文章的主題式查詢仍有缺口**（§11.5 第 5 點）。最便宜的補法（**不是現在的決定**）：因為 sitemap 現在是完整的，**重跑 `www` 的爬蟲**，`discover_sitemap()` 會把約 8.9k 個網址預先放進佇列，不需要懂新分頁；若日後要根治，再修 `_extract_js_pagination()` 以支援 `ptpagelist`（影響 `www`、`www.lib`、`cc`、`dhl.lib`、`archive.lib`）。
3. 休學鏈不受影響（只用到這些主機的人員頁）。
4. **分頁網址規則已確認（使用者在瀏覽器確認，2026-10-14）**：`https://www.nccu.edu.tw/p/403-1000-206-2.php?Lang=zh-tw` 是「校園公告」第 2 頁；也就是分頁是**靜態網址規則 `403-1000-<列表編號>-<頁碼>.php`**，不需要 JavaScript。存檔 HTML 的 `goPage(7)` 顯示該列表（編號 206）在 8/5 時共 7 頁（頁數可能已變）。後果：①修舊爬蟲很簡單（照規則產生第 2～N 頁網址）；②**`on` 不必重爬也能往更舊的公告翻頁**，只用 httpx：`recent_node` 預設只看第 1 頁，需要更長時間視窗時（例如「這個月」）再往後翻；③列表頁提供標題，可做**以標題關鍵字過濾再抓內文**的輕量主題搜尋，符合本專案「導覽加整頁閱讀」的做法。其他列表（`125` 招生公告、`42` 教師招募、`40` 徵才）的規則未逐一確認。

### 11.7 P0 步驟 3 結果（2026-10-14，休學鏈固定測試資料；httpx 16 個請求＋Chromium 9 頁）

| 項目 | 結果 |
|---|---|
| **依賴鏈第一環（休學頁）** | 現場頁面與 8/19 快照**文字完全相同**（相似度 1.0），偵測到的表單編號與快照**相同**（`QP-T01-02-05`、`QP-T01-03-02`、`QP-T01-03-04`）。官網在這七週沒有改動休學流程頁 |
| **表單 PDF（3 張）** | 全部可取得（moltke 5 個請求的轉址鏈 → `df?<token>`），**與快照的表單文字完全相同**（相似度 1.0，字數一致）；`承辦單位` 皆為「教務處註冊組」；無停用 |
| **人員頁（9 個處室，Chromium）** | 全部 200，每頁約 2.5～3.4 秒（含固定 2 秒等待）；`osa` 4 頁依 `Crawl-delay: 10` 間隔 |
| **真實的人事／內容變動：1 處** | **教務長室**頁與 8/25 索引相似度 0.924：現場頁面**已不含劉建興（分機 62442、校際 EMI 計畫業務）**；部分列改成姓氏加職稱的簡短寫法（「馬主任」「許主任」「曹秘書」「王組長」），原本的全名（許志堅、馬藹萱、曹惠莉）不在現場文字中。教務長（劉吉軒，分機 62160）兩邊都在。**這是第一個實測到的「快照與現場不同」案例**（我只能說「該頁面不再列出」，不能推論那位人員是否離職）。其餘 8 個處室的分機集合與索引一致 |
| **兩個「分機變動」是誤報** | 原資中心 `點擊數: 61207 → 62459` 與圖書館 `瀏覽數:44510 → 46137` 是**頁面瀏覽計數器**，被我腳本的 5 位數正規式誤當成分機。這驗證了 §5.2 `normalize()` 必須移除計數器（已補上 `瀏覽數`）；人員比對不能只用「5 位數」，要以職務與姓名為準（§5.9） |

**對計畫的影響**
1. **端到端的依賴鏈有了第一個真實樣本**：休學頁、表單都沒變，變的是人員頁——正好是「快照最容易過時」的那一環，與計畫的假設一致。
2. moltke 的請求數比預估多（每張表單 5 個，3 張共 15 個），且需要每張表單獨立 session（§5.7 第 7 點）；休學現場階段的 moltke 部分約 15 個請求，以每主機間隔 1 秒計至少約 15 秒（可平行 2 個 session 降到約 8 秒；moltke 間隔可覆蓋為 0.5 秒）。
3. 固定測試資料已備齊（19 個檔案＋`manifest.json`），可進入 P1：抓取器、比對、正規化的離線單元測試。

---

## 12. 未來延伸（不在原型範圍；2026-10-14 討論後記錄，避免遺失）

使用者決定：先做原型（休學鏈、`recent_node`），以下暫不考慮，日後再討論。

### 12.1 「馬上搜尋」式的未知頁面發現

- **背景（已查證官方文件）**：Claude（`web_search`＋`web_fetch`）、Gemini（Google Search grounding＋URL context）、ChatGPT（`web_search`）的即時搜尋，都是「**搜尋引擎找出候選頁面 → 再抓取內容**」，不是逐頁瀏覽網站來發現新頁面。
- 使用者的觀點：`on` 之後應該像三家一樣馬上搜尋，不限於列表第 1 頁，甚至能補足語料沒有的資料。
- 對政大而言，需要一個「搜尋」來源，選項：

| 選項 | 優點 | 限制 |
|---|---|---|
| 各站的**站內搜尋端點**（CMS 自帶） | 即時、新鮮、不出校 | 每個 CMS 格式不同，要逐一找；範圍限單一網站 |
| **外部搜尋 API＋`site:nccu.edu.tw`**（自架 SearXNG，或 Brave／Tavily 等） | 一個入口、跨網站 | 新鮮度取決於上游索引；查詢會出校；覆蓋度未知 |
| **自建索引**（sitemap 網址＋標題、現場抓取結果） | 完全可控 | 需要先抓過（見 12.2、12.3） |

- **2026-10-14 查詢（第三方資料，引用 Google 文件；未能直接驗證 Google 官方頁面，各來源對關閉日期說法不一）**：Google Custom Search JSON API 已對新客戶關閉，既有客戶須於 2027-01-01 前遷移；Google 建議改用 Vertex AI Search（最多 50 個網域）。Gemini 的 Google Search grounding 只適用於 Gemini 模型，**不適用於 Ollama 上的 Gemma**。Brave Search API 為按量計費（第三方資料約每千次查詢 US$4～5，免費額度說法不一）。Tavily、Exa 未查。因此「讓 Gemma 用 Google 搜尋」不是現成可用的選項；若日後要做，建議作為**確定性觸發的後備**（本地與列表搜尋都找不到時才呼叫，再用 `get_page` 現場抓取結果），而不是新增一個讓 Gemma 自己選用的工具；時間性查詢仍以列表頁為主（搜尋引擎索引有延遲）。要評估時，用一批真實的政大問題比較 Vertex AI Search、Brave、自架 SearXNG。

### 12.4 `recent_node` 的轉接器依 CMS「家族」設計，不是每個網站重做

- 已見到的家族（依 `preprocess.py` 註解與網址樣式，**未普查 154 個子網域**）：PageOne（`www`、`cashier`、`dean`；列表分頁為 `…-N.php`）、Joomla（`aca`、`osa`；分頁為 `?start=N`）、疑似 Drupal（`learning`，`/zh-hant/node/N`，推測）、ASP.NET（`oic`，`/Category/N`）。
- 每個家族一個轉接器：列表項目解析、分頁規則、日期格式；每個網站只是登錄表的一列（列表網址＋家族）。
- 遇到不符合任何家族的列表頁：先用確定性規則，失敗才讓 Gemma 讀整頁抽出項目與「下一頁」連結（沿用 `_llm_extract_contacts` 的模式；穩定度待量測）。
- 「9/1 之後的公告」＝時間視窗查詢：對登錄表每個列表從第 1 頁往後翻，直到整頁都早於視窗起點（置頂舊公告不能當停止條件）；`www` 另以 sitemap `lastmod ≥ 視窗起點` 交叉檢查。涵蓋範圍＝登錄表；`osa` 每頁間隔 10 秒，翻頁較慢。

### 12.2 「自動補洞」：把現場抓到的頁面逐步加入旁路索引

- 現場抓取（D2：不寫入語料庫）已規劃旁路快取；可再加一個**旁路 FTS**：每次現場抓到的頁面（網址、標題、正規化文字、時間）自動索引，之後的搜尋就找得到——語料隨使用逐步補全，不需整批重爬。
- 取捨：索引成長與清理、內容安全隔離、與被 git 追蹤的語料的關係、eval 可重現性（快照鎖定模式必須排除這份索引）。
- **原型階段只需確保旁路快取保存「網址、標題、文字、時間」**，保留這個可能；不實作索引。

### 12.3 補語料（重爬）的選項

使用者的觀點：用 Playwright 重爬才找得到使用者「真的點得到」的頁面；到時候也許不必用 Playwright。

| 做法 | 說明 | 估計（未實測） |
|---|---|---|
| sitemap 播種的重爬 | `www` 的 sitemap 已完整（8,937 筆），重跑原本的爬蟲（httpx）即可；對沒有 sitemap 的主機無效（`www.lib` 無） | `www` 約 2.5 小時 |
| 修 `_extract_js_pagination()` 支援 `ptpagelist` | 影響 `www`、`www.lib`、`cc`、`dhl.lib`、`archive.lib`；列表頁分頁網址是靜態規則 `…-N.php`（使用者在瀏覽器確認 `403-1000-206-2.php` 是校園公告第 2 頁；其他列表未逐一確認） | 小 |
| Playwright 點擊導覽 | 最貼近使用者實際看到的頁面；可只用來「學出分頁網址規則」再交給 httpx | 每頁約 4.6 秒；8.9k 頁約 11 小時 |

---

## 附錄 A：本計畫引用的已查證檔案

`docs/architecture.md`、`docs/phase_h_agentic_rag_migration_plan.md`、`docs/phase-f/phase_f_planning_report.md`、`docs/evidence/2026-09-20_resource_query_run.md`、`docs/upper_bound/evaluation.md`、`answer_quality_findings.md`、`security_and_memory_design.md`、`rag/agent_tools.py`、`rag/agentic/nodes/{plan,loop,resource,contact,synthesis,self_eval}.py`、`rag/agentic/tools/{page,form,search}.py`、`rag/agentic/state.py`、`agentic_rag.py`、`rag/preprocess.py`、`rag/fetch_moltke_forms.py`、`rag/fetch_office_contacts.py`、`rag/skills/office_lookup_skill.py`、`rag/domain_router.py`、`rag/keyword_store.py`、`output/<sub>/map.json`、`output/<sub>/crawl_report.md`、`requirements.txt`。

## 附錄 B：外部資料（套件與 america.gov）

- America.gov How it works：`https://america.gov/how-it-works`（只說明「答案來自官方網站並附連結」，未說明檢索機制）。
- Crawl4AI：`https://github.com/unclecode/crawl4ai`；多網址分派器：`https://docs.crawl4ai.com/advanced/multi-url-crawling/`。
- Firecrawl：`https://github.com/firecrawl/firecrawl`。
- Playwright MCP：`https://github.com/microsoft/playwright-mcp`。
- MCP Fetch server：`https://github.com/modelcontextprotocol/servers/tree/main/src/fetch`。
- Docling：`https://github.com/docling-project/docling`；MarkItDown：`https://github.com/microsoft/markitdown`；Trafilatura：`https://github.com/adbar/trafilatura`。
- Jina Reader：`https://github.com/jina-ai/reader`；Crawlee：`https://github.com/apify/crawlee-python`；Browser Use：`https://github.com/browser-use/browser-use`。
- Playwright browser contexts：`https://playwright.dev/python/docs/browser-contexts`。
- 以上「已查證」限於 README／官方文件所述，**均未在政大頁面上實測**。
