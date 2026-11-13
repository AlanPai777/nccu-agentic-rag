# 第 8 題（搬離宿舍如何辦理退還住宿保證金）的現場查證紀錄

經使用者批准，每個網址一次，工具 `curl`（不加 `-k`、不跟隨轉址），User-Agent `eval-research-client`，沒有使用任何個人 email；標頭裡的 `Set-Cookie` 值已遮蔽。

## 2026-11-13 約 21:00

| 請求 | 回應 | 檔案 |
|---|---|---|
| `https://osa.nccu.edu.tw/tw/住宿輔導組/宿舍申請與床位資訊/退離宿程序`（住宿輔導組「退離宿程序」） | 200，89,837 位元組 | `osa_exit_procedure.html`、`.headers.txt` |
| `https://osa.nccu.edu.tw/tw/faq`（學務處 FAQ） | 200，288,972 位元組 | `osa_faq.html`、`.headers.txt` |
| `https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-M03-01-05`（離宿暨退還住宿保證金申請表） | 302，`Location: login.formservice?viewdetail=QP-M03-01-05`（同一站台的登入頁，沒有跟隨），內容 0 位元組 | `moltke_QP-M03-01-05.headers.txt` |

**結果**：現場頁面與本機快照一致：學期中流程（填表 → 持表到宿舍服務台檢查寢室簽章 → 三天內持表及宿費繳費收據到住宿組（行政大樓3樓）辦理退宿註記、退宿費或住宿保證金）、備註（僅退保證金者可不交收據、由住宿組造冊匯入個人基本資料登記的帳戶、期末離宿日前一週內離宿者可轉交、僑外生代領人）、FAQ（住宿保證金 1,000 元、未依退離宿程序辦理者保證金不予退還、畢業休學退學轉學的住宿生發生日起 7 日內）。表單連結仍列在頁面上，與其他 moltke 連結一樣回 302 轉登入頁，連結本身有效、看不到表單內容；表單內容以快照為準。
