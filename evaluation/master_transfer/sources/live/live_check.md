# 第 7 題（碩士班轉系所需要經過哪些單位同意）的現場查證紀錄

經使用者批准，每個網址一次，工具 `curl`（不加 `-k`、不跟隨轉址），User-Agent `eval-research-client`，沒有使用任何個人 email；標頭裡的 `Set-Cookie` 值已遮蔽。

## 2026-11-13 約 20:20

| 請求 | 回應 | 檔案 |
|---|---|---|
| `https://aca.nccu.edu.tw/zh/服務項目/學籍/轉系`（教務處「轉系／轉所」頁面） | 200，260,132 位元組 | `aca_transfer_page.html`、`.headers.txt` |
| `https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-05-05`（碩士班轉系所申請書） | 302，`Location: login.formservice?viewdetail=QP-T01-05-05`（同一站台的登入頁，沒有跟隨），內容 0 位元組 | `moltke_QP-T01-05-05.headers.txt` |
| `https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-05-06`（碩士轉系所學分認定申請書） | 302，`Location: login.formservice?viewdetail=QP-T01-05-06`，內容 0 位元組 | `moltke_QP-T01-05-06.headers.txt` |

**結果**：現場頁面仍列有碩士班轉所的全部規定（修業第二學年開始前、原肄業所及擬轉入所雙方主管同意、以一次為限、申請期間 12/1–12/31 與 6/1–6/30、一般研究所與在職專班不得互轉、申請當學期不得休學…），與本機快照一致；兩個表單連結仍列在頁面上（寫成 `[文字](網址)`）。兩個 moltke 連結與其他表單一樣回 302 轉登入頁，連結本身有效、看不到表單內容；表單內容以快照為準。

## 2026-11-15 補查（使用者批准 1 次請求）

| 網址 | 結果 | 存檔 |
|---|---|---|
| `https://aca.nccu.edu.tw/download/rulesdata/law01A.pdf`（學則） | 200，`application/pdf`，360,410 位元組，`Last-Modified: Wed, 19 Feb 2025`，沒有轉址 | `aca_law01A.pdf`、`aca_law01A.pdf.headers.txt`（`Set-Cookie` 沒有出現）；轉成文字 `aca_law01A.pdf.txt`（pdfplumber，13 頁，離線） |

用途：K21（各所轉所名額以核定招生名額一成為原則）的現場出處，原文在現場 PDF 逐字找得到。請求方式：`curl -sS -m 40 -A eval-research-client -D <標頭檔> -o <檔案>`，沒有 `-k`、沒有跟隨轉址、只這一次。
