# 2026-11-09 現場查證紀錄（出納組電話題）

經使用者逐步批准，只請求下列 URL，沒有爬取其他頁面。User-Agent 使用通用名稱 `eval-research-client`。

## 1. 舊網址：回 301 轉址，沒有頁面內容

出納組網站缺中繼憑證（專案的 `INSECURE_TLS_HOSTS` 有列），所以這兩次請求用 `curl -k` 略過憑證驗證。**原始標頭當時只印在終端機，沒有存成檔案**，下表是當時終端機輸出的 `Location` 行，不是原始標頭檔。

| 請求 | 回應 |
|---|---|
| `https://cashier.nccu.edu.tw/` | `301 Moved Permanently`，`Location: https://nccuga.nccu.edu.tw/zh/` |
| `https://cashier.nccu.edu.tw/PageStaffing?fid=7994` | `301 Moved Permanently`，`Location: https://nccuga.nccu.edu.tw/zh/PageStaffing?fid=7994` |

結論：出納組網站已併入總務處網站（`nccuga.nccu.edu.tw`）。

## 2. 新網址：有原始標頭檔與頁面檔（同目錄）

| 請求 | 結果 | 檔案 |
|---|---|---|
| `https://nccuga.nccu.edu.tw/zh/` | 200 | `nccuga_home.html`、`nccuga_home.headers.txt` |
| `https://nccuga.nccu.edu.tw/zh/PageStaffing?fid=7994` | **404** | `nccuga_staffing_fid7994_404.html`、`.headers.txt` |
| `https://nccuga.nccu.edu.tw/zh/各組服務項目/出納組?view=default` | 200 | `nccuga_cashier_service.html`、`.headers.txt` |
| `https://nccuga.nccu.edu.tw/zh/關於我們/聯絡資訊` | 200 | `nccuga_contact_info.html`、`.headers.txt` |

抓取時間：2026-11-09 約 21:12 起（台北時間，標頭 `Date` 為 GMT 13:12）。

## 3. 查證結果

- 三個 200 頁面的頁尾都寫「**出納組分機 62120**」與「(02)2939-3091」。
- 「聯絡資訊」頁本文寫「總務處 (02)2939-3091 **分機62095**」，這是總務處，不是出納組。
- 舊站的出納組人員頁（`fid=7994`）在新站不存在（404），所以快照中的人員資料與 62123 等其他分機**無法用現場資料確認**。

## 3. 2026-11-14 補查（62119 是否仍被官方文件列為出納組電話）

經使用者逐一批准，各請求一次，不跟轉址，`curl -sS -m 40 -A eval-research-client`，標頭已去除 `Set-Cookie`。

| 請求 | 結果 | 檔案 |
|---|---|---|
| `https://aca.nccu.edu.tw/zh/最新消息/註冊組-2/5792-115學年度第1學期註冊通知單相關事宜（8-3更新）` | 200；頁面全文沒有 62119，附 PDF 連結 | `aca_news5792_115-1.html`、`aca_news5792_115-1.headers.txt` |
| `https://aca.nccu.edu.tw/db/upload/115-1註冊通知單_中文版.pdf` | 200；寫「出納組聯絡電話：02-29393091轉62119-62123、62125-62127、62172、62173」 | `aca_notice_115-1.pdf`、`aca_notice_115-1.txt`（pdfplumber 文字）、`aca_notice_115-1.headers.txt` |

結論：62119 仍被官方通知單列為出納組聯絡電話（只是人員頁沒有對應人員），所以保留在允許集合；通知單的範圍不含 62124。
