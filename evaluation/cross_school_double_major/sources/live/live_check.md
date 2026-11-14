# 第 11 題（政大學生跨校修讀台聯大雙主修需要經過哪些單位審核）的現場查證紀錄

經使用者批准，每個網址一次，工具 `curl`（不加 `-k`、不跟隨轉址），User-Agent `eval-research-client`，沒有使用任何個人 email；標頭裡的 `Set-Cookie` 值已遮蔽。

## 2026-11-14 約 14:07

| 請求 | 回應 | 檔案 |
|---|---|---|
| `https://aca.nccu.edu.tw/zh/專區業務/newbie-2/150-跨校修讀雙主修輔系/4963-跨校修讀雙主修輔系`（教務處「跨校修讀雙主修輔系」專區頁） | 200，266,800 位元組 | `aca_cross_school_page.html`、`.headers.txt` |
| `https://aca.nccu.edu.tw/db/upload/台灣聯合大學系統學生跨校修讀雙主修辦法.pdf`（台聯大跨校修讀雙主修辦法） | 200，`application/pdf`，89,828 位元組 | `ust_double_major_law.pdf`、`.headers.txt`；轉成文字 `ust_double_major_law.pdf.txt`（pdfplumber，離線） |

moltke 表單 QP-T01-04-21 的連結沒有送請求（moltke 連結一律 302 轉登入頁，其他題已驗證）；連結以教務處專區頁現場版本上列出的為準。政大註冊組的人員頁已在登記表（`evaluation/registry/`），這題沒有再抓。

**結果**：
- 專區頁現場與快照一致：碩博士班不開放雙主修及輔系、申請原則（僅限性質不同之學系、須經雙方同意）、申請資格（學士班一年級下學期起至三年級止）、作業期間（原則每年 5 月底公告、7 月受理、8 月下旬公布榜單）、「不得以他校雙主修學系畢業」、三份表單連結都還在；115 學年度的年度公告（7/1–7/23、8/31）也還在（不收）。
- 辦法 PDF 的現場文字與快照正規化後逐字相同（1041 字）。
- 專區頁的複本另放在 `evaluation/registry/sources/live/aca_cross_school_page.html`（登記表的表單來源引用那一份）。
