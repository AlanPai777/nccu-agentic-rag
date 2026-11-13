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

