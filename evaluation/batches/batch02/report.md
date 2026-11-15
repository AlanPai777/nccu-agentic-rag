# batch02 跨題報告

- live：True；瀏覽器：True；模型：gemma4:31b-cloud；git：4910e8e；建立：2026-11-15T17:26:21+08:00
- 限制：每題只跑一次，LLM 有隨機性；現場頁面會隨時間變，`prediction.json` 是系統當時看到的唯一記錄；隔離回推是否真的隔離看每題 `trace.json` 的 judge 註記與稽核結果。

## 每題

### Q1 cashier_contact — ok（run03，16.2 秒）
- 階段 3 已算分：Completeness 0.6667、Hallucination 0.0；漏斗 [{"id": "K1", "in_context": false, "stated_correctly": false, "grounded": false, "verdict": "irrelevant"}, {"id": "K2", "in_context": false, "stated_correctly": true, "grounded": true, "verdict": "relevant"}, {"id": "K3", "in_context": true, "stated_correctly": true, "grounded": true, "verdict": "re
- 現場讀取：live_same×1

## live 與轉址觀察（F19）

- 全批現場讀取狀態：live_same×1
- 走到轉址的頁面：沒有（預期：只有第 1 題與提到出納組的第 8 題可能走到總務處人員頁）
- 渲染（Chromium）次數沒有寫進 prediction；要看見它，請讀 `logs/Qxx.log`（已開 `LIVE_LOG=info`）。
