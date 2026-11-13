# 2026-11-13 現場查證紀錄（休學申請表下載題）

經使用者批准，只請求下列 3 個 URL，每個一次，沒有爬取其他頁面。工具 `curl`（不加 `-k`、不跟隨轉址），User-Agent 使用通用名稱 `eval-research-client`，沒有使用任何個人 email。請求間隔 2 秒。
抓取時間：2026-11-13 約 13:48 起（台北時間；伺服器標頭 `Date` 為 GMT 05:48 到 05:50，兩個時鐘差約 2 分鐘）。

| 請求 | 回應 | 檔案 |
|---|---|---|
| `https://aca.nccu.edu.tw/zh/服務項目/學籍/休學-保留學籍-退學-提早復學` | 200 | `aca_leave_page.html`、`.headers.txt` |
| `https://aca.nccu.edu.tw/en/form-download` | 200 | `aca_form_download_en.html`、`.headers.txt` |
| `https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-03-02` | **302**，`Location: login.formservice?viewdetail=QP-T01-03-02`（同一主機的登入頁），沒有頁面內容 | `moltke_QP-T01-03-02.headers.txt` |

## 查證結果

- 兩個教務處頁面現場**仍然列有同一個連結** `https://moltke.nccu.edu.tw/formservice_SSO/link.jsp?viewdetail=QP-T01-03-02`：中文頁在「相關法規與表單」下，文字是「休學/保留學籍申請書」；英文表單下載頁的文字是「Application Form for Leave of Absence or Retainment of Student Status(休學(保留學籍)申請書)」。與快照一致。
- **moltke 的表單連結本身回 302 轉到登入頁**（`login.formservice?viewdetail=QP-T01-03-02`，`formservice_SSO` 是單一登入的表單服務）。依約定**沒有跟隨**，所以不知道登入之後會看到什麼、是不是需要校內帳號才能下載。這一點只記錄，不影響 gold：標準答案是教務處頁面列出的下載連結。
- 標頭檔裡的 `Set-Cookie: JSESSIONID` 值已遮蔽（匿名 session，沒有保留的必要），其餘是伺服器原始標頭。
- 沒有請求的頁面：登入頁本身（`login.formservice?...`，同一主機，未經批准不請求）、moltke 的其他表單。
