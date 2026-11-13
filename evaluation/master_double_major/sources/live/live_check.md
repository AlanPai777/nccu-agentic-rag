# 第 9 題（碩士班雙主修輔系申請需要經過哪些單位審核）的現場查證紀錄

經使用者批准，每個網址一次，工具 `curl`（不加 `-k`、不跟隨轉址），User-Agent `eval-research-client`，沒有使用任何個人 email；標頭裡的 `Set-Cookie` 值已遮蔽。

## 2026-11-13 約 21:50

| 請求 | 回應 | 檔案 |
|---|---|---|
| `https://aca.nccu.edu.tw/zh/服務項目/雙主修-輔系-學程/碩博士班雙修輔系`（教務處「碩博士班雙修輔系」） | 200，257,027 位元組 | `aca_double_major_page.html`、`.headers.txt` |
| `https://aca.nccu.edu.tw/download/rulesdata/law131A.pdf`（碩博士班學生修讀雙主修、輔系辦法） | 200，`application/pdf`，74,251 位元組 | `aca_law131A.pdf`、`.headers.txt`；轉成文字 `aca_law131A.pdf.txt`（pdfplumber，離線） |
| `https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-03-08`（碩、博士班學生修讀雙主修／輔系申請表） | 302，`Location: login.formservice?viewdetail=QP-T01-03-08`（同一站台的登入頁，沒有跟隨），內容 0 位元組 | `moltke_QP-T01-03-08.headers.txt` |

**結果**：現場頁面與本機快照一致：申請對象（碩博士班學生，自註冊在學第二學期起至第四學期止，經就讀學系所同意，向招收修讀雙主修或輔系的學系所提出）、申請時間（每年四月下旬至五月上旬，依行事曆公告）、申請方式（經就讀學系所核章後，併同其他申請資料送申請雙輔學系所審查）、碩士在職專班不開放；辦法 PDF 仍在，第 2、3 條的文字與快照一致。表單連結仍列在頁面上，與其他 moltke 連結一樣回 302 轉登入頁，連結本身有效、看不到表單內容；表單內容以快照為準。
