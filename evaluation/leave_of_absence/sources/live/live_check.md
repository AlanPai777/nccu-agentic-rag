# 第 5 題（如何辦理休學）的現場查證紀錄

（與 `evaluation/registry/sources/live/live_check.md` 同一批請求；這題用到的現場頁面存一份在這裡，因為 gold 的引句驗證只讀這一題自己的 `sources/`。）

## 靜態抓取（curl，通用 User-Agent `eval-research-client`，不跟隨轉址）：第 3 題與第 4 題已查

- 教務處「休學-保留學籍-退學-提早復學」頁面（`aca_leave_page.html`，2026-11-13）：200。
- 學務處「休（退）學退費標準」（`osa_refund_standard.html`，2026-11-13）：200。

## 動態抓取（`evaluation/registry/fetch_live_page.py`，Chromium 預設 User-Agent，不含 email）：2026-11-13，使用者批准

| 頁面 | 檔案 | 結果 |
|---|---|---|
| 住宿輔導組成員（約 17:08） | `osa_staff_dorm.rendered.html` | 200 |
| 圖書館典藏閱覽組（約 17:08） | `lib_staff_circulation.rendered.html` | 200 |
| 原資中心成員（約 17:08） | `osa_staff_indigenous.rendered.html` | 200 |
| 出納組舊網址 `cashier.nccu.edu.tw/PageStaffing?fid=7994`（約 17:08） | 只有 `cashier_staff.render.json` | **404**（網站搬家，舊人員頁已不存在） |
| 總務處 8 個單位的新人員頁（約 17:50）：總務長室、文書組、事務組、財產組、營繕組、出納組、環安組、規劃組 | `ga_*.rendered.html` | 全部 200 |

總務處 8 個新頁面是 `https://nccuga.nccu.edu.tw/zh/人員職掌選單/<單位名稱>_`（各 `.render.json` 有完整網址）。
這題的 gold 只有出納組（`ga_cashier`）相關；其餘 7 頁（`ga_dean`、`ga_docu`、`ga_aff`、`ga_wealth`、`ga_mend`、`ga_safety`、`ga_planning`）是使用者決定一併保存的，記錄這次網站更新的範圍（議題 F19）。
完整的請求細節（工具、時間、位元組、請求數）見登記表那份 `live_check.md`。
