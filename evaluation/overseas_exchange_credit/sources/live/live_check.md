# 第 10 題（出國交換學分抵免，體育、通識、外文通識分別送哪個單位）的現場查證紀錄

經使用者批准，每個網址一次。一般頁面與 PDF 用 `curl`（不加 `-k`、不跟隨轉址，User-Agent `eval-research-client`，沒有使用任何個人 email；標頭裡的 `Set-Cookie` 值已遮蔽）。人員頁一律用 `evaluation/registry/fetch_live_page.py`（無頭 Chromium、預設 User-Agent），結果放在 `evaluation/registry/sources/live/`。

## 2026-11-14 約 12:18–13:06

| 請求 | 回應 | 檔案 |
|---|---|---|
| `https://aca.nccu.edu.tw/zh/服務項目/成績-抵免/學分抵免（含新生及出國）-整合`（教務處「學分抵免」頁） | 200 | `aca_credit_page.html`、`.headers.txt` |
| `https://aca.nccu.edu.tw/download/rulesdata/law06A.pdf`（學生抵免學分辦法） | 200，`application/pdf`，195,556 位元組 | `aca_law06A.pdf`、`.headers.txt`；轉成文字 `aca_law06A.pdf.txt`（pdfplumber，離線） |
| `https://aca.nccu.edu.tw/zh/人員職掌-通識`（通識教育中心人員頁，動態） | 200 | `registry/sources/live/aca_staff_gec.rendered.html` |
| `https://sports.nccu.edu.tw/web/about/staff.jsp`（體育室行政人員，動態） | 200 | `registry/sources/live/sports_staff.rendered.html` |
| `https://flc.nccu.edu.tw/zh_tw/About/Administrative`（外文中心行政團隊，動態） | 200 | `registry/sources/live/flc_staff.rendered.html` |
| `https://aca.nccu.edu.tw/zh/最新消息/通識教育中心-3/5318-課程地圖使用情況與滿意度調查`（通識中心樓層的輔助出處） | 200 | `registry/sources/live/gec_news_5318.html` |
| `https://gecenter.nccu.edu.tw/student-zone/gec-credit-waiver/credits-from-overseas-exchange-programs`（通識教育中心「國外交換學分認抵本校一般通識學分」，語料裡的網址，無結尾斜線） | **301**，`Location` 是同一網址加結尾斜線（WordPress 轉址），內容只有 187 位元組的快取註解，沒有跟隨 | `gec_overseas_credit_page.html`、`.headers.txt`（轉址回應，不是頁面內容） |
| `https://gecenter.nccu.edu.tw/student-zone/gec-credit-waiver/credits-from-overseas-exchange-programs/`（轉址後的網址，另行批准） | 200，124,985 位元組 | `gec_overseas_credit_page_slash.html`、`.headers.txt` |

三個人員頁與通識新聞頁的檔案另外複製了一份在這個資料夾（`aca_staff_gec.*`、`sports_staff.*`、`flc_staff.*`、`gec_news_5318.*`），登記表引用的仍是 `evaluation/registry/sources/live/` 那一份。

moltke 表單 QP-T01-04-05 的連結沒有送請求（moltke 連結一律 302 轉登入頁，其他題已驗證）；連結以教務處現場頁面上列出的為準。

**結果**：
- 教務處「學分抵免」頁的出國交換段（辦理對象、辦理時間、辦理方式一至三、申請表連結、逾期處理）與快照一致。
- 辦法 law06A 仍是民國 115 年 7 月 30 日發布版；第 5 條、第 7 條（外文通識由外文中心審查、一般通識及書院通識由通識教育中心審查、體育課程由體育室審查；送註冊組複查、教務長核定）與快照一致。
- 通識教育中心頁面（加斜線的網址）的現場內容與快照一致：「學生於出國學期結束後，應備齊申請文件，於次學期三分之一基準日前洽通識教育中心辦理」、成績證明須蓋「與正本相符」戳記、「核心通識不得抵免」都在。
- 三個審查單位的人員與分機都與快照一致（通識中心姓名欄改成姓＋職稱寫法；外文中心推廣教育的分機由 67103 變 63471、另多一位雙語計畫專員，與本題無關）。
