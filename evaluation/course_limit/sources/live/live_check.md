# 2026-11-11 現場查證紀錄（選課上限題）

分兩輪，每輪都經使用者批准，共 7 個 URL，每個一次，沒有爬取其他頁面。第一輪 5 個（下表），第二輪 2 個（見「第二輪」）。工具 `curl`（不加 `-k`、不跟隨轉址），User-Agent 使用通用名稱 `eval-research-client`，沒有使用任何個人 email。請求間隔 2 秒。
抓取時間：2026-11-11 約 20:00 起（台北時間；伺服器標頭 `Date` 為 GMT 12:02，兩個時鐘差約 1.5 分鐘）。5 個請求全部回 `200`，沒有轉址、沒有憑證錯誤。原始標頭與內容都存在本目錄。

| 請求 | 回應 | 檔案 | 伺服器 `Last-Modified` |
|---|---|---|---|
| `https://aca.nccu.edu.tw/download/rulesdata/law01A.pdf` | 200 | `aca_law01A.pdf`、`.headers.txt`、`.txt` | 2025-02-19 |
| `https://aca.nccu.edu.tw/zh/常用連結/教務處qa/選課業務` | 200 | `aca_faq_course_selection.html`、`.headers.txt` | 頁面動態產生（等於抓取時間） |
| `https://aca.nccu.edu.tw/download/course/選課須知11407.pdf` | 200 | `aca_course_notice_11407.pdf`、`.headers.txt`、`.txt` | 2025-07-28 |
| `https://aca.nccu.edu.tw/download/course/選課Q&A_11407.pdf` | 200 | `aca_course_qa_11407.pdf`、`.headers.txt`、`.txt` | 2025-07-21 |
| `https://aca.nccu.edu.tw/zh/` | 200 | `aca_home.html`、`.headers.txt` | 頁面動態產生 |

PDF 的 `.pdf.txt` 是 `build_gold.py` 用 pdfplumber 從現場 PDF 轉出的純文字（每次建 gold 都重新產生），供 `evaluation/gold_check.py` 逐字驗證用；HTML 不另存文字檔，驗證時直接從 `.html` 去掉標籤。

## 查證結果

- 學則第十五條、教務處 QA「選課業務」、選課須知（114.07）、選課 Q&A（114.07）四份，與 2026-08 快照的關鍵語句**逐字一致**：學士班上限 25、第一至三學年下限 12、第四學年下限 10、雙主修 31、輔系 28、無加修學系 25、超減修至多 6 學分、碩博士班由各系所自定。
- 選課須知與選課 Q&A 在伺服器上仍是 `11407`（114.07）版；從這 5 個頁面看不到 115 學年的新版選課須知（首頁有「選課」「本校選課」等連結，但這次沒有請求那些頁面）。
- **沒有找到任何一句明說「超修後每學期最高 31 學分」**。31 只出現在選課須知「具雙主修身分者…提高為31學分」。依使用者的決定，這一點沒有找到原文就**不列入 gold**。
- 首頁的兩個可能相關連結（`/zh/身份索引/學士班學生/選課?view=default`、`/zh/服務項目/選課/本校選課-整合`）第一輪沒有請求，經使用者批准後在第二輪請求，結果見下。

## 第二輪（2026-11-11 約 20:04 起，使用者批准，方法同上）

| 請求 | 回應 | 檔案 |
|---|---|---|
| `https://aca.nccu.edu.tw/zh/身份索引/學士班學生/選課?view=default` | 200，無轉址 | `aca_student_undergrad_course_selection.html`、`.headers.txt` |
| `https://aca.nccu.edu.tw/zh/服務項目/選課/本校選課-整合` | 200，無轉址 | `aca_course_selection_integrated.html`、`.headers.txt` |

結果：兩頁都是**導覽頁**，沒有任何學分上限的敘述（使用者事先就預期如此）。頁面連結出去的相關文件有：超減修申請流程（`/download/flowProcess/file/register/register18.pdf`）、115選課說明、選課須知（連結仍是 `選課須知11407.pdf`，所以 114.07 版仍是現行版）、本校學生選課辦法（`/download/rulesdata/law04A.pdf`）。這四份**沒有現場請求**，只查了本地快照：超減修流程與選課辦法的快照內容都**沒有**「最高 31」的明文。結論不變：沒有找到 → 不列入 gold。

**保存方式**：這兩頁與首頁（`aca_home.html`）共 3 個 HTML（連同 `.headers.txt`）gold 沒有引用，只是「沒找到」的證據，所以**只留在本機、不進 git**（`.gitignore` 有列）；進 git 的是本檔的文字記錄。
