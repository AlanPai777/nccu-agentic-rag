# 單位登記表的現場查證紀錄

經使用者批准，每個網址一次。工具 `curl`（不加 `-k`、不跟隨轉址），User-Agent 使用通用名稱 `eval-research-client`，沒有使用任何個人 email。標頭裡的 `Set-Cookie`（防偽造權杖）值已遮蔽，其餘是伺服器原始標頭。

## 2026-11-13 約 15:38（台北時間；伺服器標頭 `Date` 為 GMT 07:41）

| 請求 | 回應 | 檔案 |
|---|---|---|
| `https://oic.nccu.edu.tw/Category/596`（國合處工作職掌） | 200，58,794 位元組，無轉址 | `oic_category_596.html`、`oic_category_596.html.headers.txt` |

**結果**：原始 HTML 轉成文字只有 136 行，全部是網站的選單與頁尾連結（國際學生、本地學生、教職員工、關於我們、聯絡我們…），**沒有任何人員、分機、職掌**。人員資料是 JavaScript 動態載入的，靜態請求拿不到。

這與 `output/office_contacts_index.jsonl` 的國合處那筆（2026-08-25 動態抓取、203 行，有學歷、現任、職掌、分機、信箱，但沒有姓名與職稱）一致：索引那次是用瀏覽器渲染抓的。

**頁面選單裡可能有人名與職稱的網址（沒有請求，需要使用者批准）**：
- `/Category/176` 成員及組織架構
- `/Post/15885` 歷任國合長
- `/Post/15887` 國合處介紹
- `/Post/800` 國合處聯絡方式（語料已有快照，地址、總機、各組樓層）

## 2026-11-13 約 15:40：動態請求（使用者批准）

使用者批准用專案自己的動態抓取請求 `Category/596`。工具：`evaluation/registry/fetch_live_page.py`（呼叫 `rag/live/browser.py` 的 `PlaywrightBackend`：無頭 Chromium，開網址、等 load、再等 2000 毫秒讓 JavaScript 補內容、取 DOM；每次用全新的 context；只允許 `*.nccu.edu.tw`）。**沒有設定 User-Agent**，Chromium 送它的預設值，不含任何 email（這與 `curl` 用的 `eval-research-client` 不同，是專案做索引時的做法，這樣抓回來的頁面可以跟索引比較）。瀏覽器載入頁面時會發出頁面本身用到的多個請求。

| 請求 | 回應 | 檔案 |
|---|---|---|
| `https://oic.nccu.edu.tw/Category/596`（動態） | 200，渲染後 118,415 位元組；頁面共發出 37 個請求（其中 `*.nccu.edu.tw` 22 個），3.3 秒 | `oic_category_596.rendered.html`、`oic_category_596.render.json` |

**結果**：渲染後的頁面有人員。每個人是「姓氏加小姐或先生」（主管是全名）、職稱、職掌、分機、信箱，分成國合長室、合作交流組、國際教育組、發展策劃組、大陸事務組五個區塊，共 35 個分機；頁尾有地址「行政大樓8樓」、信箱 oic@nccu.edu.tw、電話「886-2-29393091 #62040」。靜態 HTML 只有選單，索引（2026-08-25）那筆有職掌、分機、信箱但缺姓名與職稱，這次的渲染結果補上了。

## 2026-11-13 約 15:42：使用者批准的其餘請求

使用者批准：兩個人員頁用動態請求（`fetch_live_page.py`，同上，Chromium 預設 User-Agent，不含 email），其餘網址用 `curl`（`eval-research-client`、不加 `-k`、不跟隨轉址、間隔 2 秒，標頭裡的 `Set-Cookie` 值已遮蔽）。**登記表的人員頁一律用動態請求，每一個網址仍然逐個請使用者批准**（使用者的決定）。

| 請求 | 方式 | 回應 | 檔案 |
|---|---|---|---|
| 教務處「人員職掌-註冊」`aca.nccu.edu.tw/zh/人員職掌-註冊` | 動態 | 200，295 KB，頁面發出 30 個請求（`*.nccu.edu.tw` 26 個），3.5 秒 | `aca_staff_registrar.rendered.html`、`.render.json` |
| 學務處生僑組「成員介紹」 | 動態 | 200，138 KB，56 個請求（`*.nccu.edu.tw` 48 個），2.5 秒 | `osa_staff_soa.rendered.html`、`.render.json` |
| 註冊通知單 115-1（`aca.nccu.edu.tw/db/upload/115-1註冊通知單_中文版.pdf`） | 靜態 | 200，PDF 635 KB | 存在 `evaluation/resumption/sources/live/aca_notice_115_1.pdf` |
| `oic.nccu.edu.tw/Post/800`（國合處聯絡方式） | 靜態 | 200 | `oic_post_800.html` |
| `oic.nccu.edu.tw/Post/788`（外國學位生申請入學） | 靜態 | 200 | `oic_post_788.html` |
| 學務處「休（退）學退費標準」 | 靜態 | 200 | `osa_refund_standard.html` |

**發現**：
- 註冊組的現場頁面（2026-11-13）**只顯示「姓氏加職稱」**（例如「王組長」「黃行政專員」「呂行政專員」），索引（2026-08-25）裡是全名（王揚忠、黃婉綝、呂依潔）；分機沒變，兩邊可以用分機對起來。
- 生僑組的現場頁面仍然是全名與英文名、職稱、分機、信箱、職掌，與索引一致；頁尾地址「行政大樓三樓」。


## 2026-11-13 約 17:08：第 5 題（如何辦理休學）的人員頁（使用者批准這 4 個網址，動態請求，每個一次）

工具與條件同上（`fetch_live_page.py`，Chromium 預設 User-Agent，不含 email，settle 毫秒見各 `.render.json`）。

| 請求 | 回應 | 檔案 |
|---|---|---|
| `https://cashier.nccu.edu.tw/PageStaffing?fid=7994`（出納組人員） | **404**（`http_4xx`），沒有內容；沒有重試 | `cashier_staff.render.json`（沒有 `.rendered.html`） |
| `https://osa.nccu.edu.tw/tw/住宿輔導組/關於我們/成員介紹`（住宿輔導組成員） | 200，290,873 位元組，56 個請求 | `osa_staff_dorm.rendered.html`、`.render.json` |
| `https://www.lib.nccu.edu.tw/p/404-1000-537.php?Lang=zh-tw`（圖書館典藏閱覽組） | 200，71,221 位元組，22 個請求 | `lib_staff_circulation.rendered.html`、`.render.json` |
| `https://osa.nccu.edu.tw/tw/原資中心/關於我們-原資中心/成員介紹-原資中心`（原資中心成員） | 200，129,264 位元組，56 個請求 | `osa_staff_indigenous.rendered.html`、`.render.json` |

**發現**：出納組的人員頁這次回 404。第 1 題 gold 的現場查證（2026-11-09）當時這個網址是通的；網站可能改了網址，需要另外找新網址（要使用者批准才能再請求）。

## 2026-11-13 約 17:50：總務處 8 個單位的新人員頁（使用者提供網址並說「開始」，動態請求，每個一次）

背景：總務處各單位原本有自己的子網域（dean、docu、aff、wealth、mend、cashier、cpds），人員頁已整批搬到 `nccuga.nccu.edu.tw/zh/人員職掌選單/<單位>_`；舊網址 `cashier` 的人員頁 301 轉到新站後 404（第 1 題與本節上方的紀錄）。工具與條件同上（`fetch_live_page.py`，Chromium 預設 User-Agent，不含 email，不跟隨轉址）。

| 單位 | 檔案 | 結果 |
|---|---|---|
| 總務處長室 | `ga_dean.rendered.html`、`.render.json` | 200 |
| 文書組 | `ga_docu.…` | 200 |
| 事務組 | `ga_aff.…` | 200 |
| 財產組 | `ga_wealth.…` | 200 |
| 營繕組 | `ga_mend.…` | 200 |
| 出納組 | `ga_cashier.…` | 200 |
| 環安組 | `ga_safety.…` | 200 |
| 規劃組 | `ga_planning.…` | 200 |

網址是 `https://nccuga.nccu.edu.tw/zh/%E4%BA%BA%E5%93%A1%E8%81%B7%E6%8E%8C%E9%81%B8%E5%96%AE/<單位名稱的百分比編碼>_`（單位名稱依序是 總務長室、文書組、事務組、財產組、營繕組、出納組、環安組、規劃組；每個請求的完整網址見各 `.render.json`）。

## 2026-11-13 約 19:10：第 6 題（圖書館電話）——圖書館各組聯絡資訊頁（使用者批准這 1 個網址，動態請求，一次）

| 請求 | 回應 | 檔案 |
|---|---|---|
| `https://www.lib.nccu.edu.tw/p/404-1000-312.php?Lang=zh-tw`（圖書館「各組聯絡資訊」） | 200，63,261 位元組，22 個請求 | `lib_contact_units.rendered.html`、`.render.json` |

**結果**：頁首「政大總機：(02)29393091」「總圖 63222，綜圖 50107，商圖 84006，傳圖 67152」「達賢圖：(02)82377017」；表格中典藏閱覽組直撥顯示 `(02)2938-7878`、校內分機 63222。**典藏閱覽組那一格的連結目標（`tel:`）是 `+886229393091`（學校總機），與顯示的 `(02)2938-7878` 不一致**；其他各組的連結目標與顯示相同。本機語料另有兩個來源把圖書館直撥寫成 `(02)2938-7878`（統計系「常用行政電話」頁），顯示文字有獨立佐證，連結目標視為連結本身的筆誤。

## 2026-11-13 約 20:20：第 7 題（碩士班轉系所）——教務處「轉系／轉所」頁面與兩張表單連結（使用者批准，curl，每個一次）

教務處頁面 200（`aca_transfer_page.html`）；`QP-T01-05-05`、`QP-T01-05-06` 兩個 moltke 連結都是 302 轉登入頁，沒有跟隨（`moltke_QP-T01-05-0*.headers.txt`）。細節見 `evaluation/master_transfer/sources/live/live_check.md`。

## 2026-11-13 約 21:00：第 8 題（住宿保證金）——住宿組「退離宿程序」頁、學務處 FAQ、表單連結（使用者批准，curl，每個一次）

「退離宿程序」頁 200（`osa_exit_procedure.html`）、FAQ 200（`osa_faq.html`，只存在第 8 題資料夾）、`QP-M03-01-05` 的 moltke 連結 302 轉登入頁，沒有跟隨（`moltke_QP-M03-01-05.headers.txt`）。細節見 `evaluation/dorm_deposit/sources/live/live_check.md`。
