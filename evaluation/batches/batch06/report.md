# batch06 跨題報告

- live：True；瀏覽器：True；模型：gemma4:31b-cloud；git：dde1c24；建立：2026-11-15T19:18:48+08:00
- 指標版本：2026-11-15.context-recall-judged（Context 句子 Recall 由 Claude 判斷，不是字串比對；Sentence Precision 與 Words 指標仍是字串比對，Sentence F1 混合；此版本之前的 Context 數字不能直接比較）
- 限制：每題只跑一次，LLM 有隨機性；現場頁面會隨時間變，`prediction.json` 是系統當時看到的唯一記錄；隔離回推是否真的隔離看每題 `trace.json` 的 judge 註記與稽核結果。

## 每題

### Q2 course_limit — ok（run01，61.3 秒）
- 階段 3 已算分：Completeness 1.0、Hallucination 0.0；漏斗 [{"id": "K1", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict": "relevant"}, {"id": "K2", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict"
- 現場讀取：live_changed×2、live_same×2

### Q3 leave_form_download — ok（run01，68.3 秒）
- 階段 3 已算分：Completeness 1.0、Hallucination 0.0；漏斗 [{"id": "K1", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict": "relevant"}, {"id": "K2", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict"
- 現場讀取：live_changed×7、live_same×2

### Q4 resumption — ok（run01，83.3 秒）
- 階段 3 已算分：Completeness 0.875、Hallucination 0.0；漏斗 [{"id": "K1", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict": "relevant"}, {"id": "K2", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict"
- disagreement：{"keypoint": "K15", "rule": "wrong", "claude": "relevant", "claude_reason": "答案寫註冊組聯絡人鄧編審 63277、王組長 63273，與登記表一致（規則版把後面清單編號的數字接在分機後面，誤判配對，見 disagreements）", "rule_detail": {}}
- disagreement：{"keypoint": "K17", "rule": "wrong", "claude": "relevant", "claude_reason": "答案寫生僑組盧翠婷（組長）63010、黃信翰（一級行政專員）63011，與登記表一致", "rule_detail": {}}
- 現場讀取：live_changed×7、live_same×5

### Q5 leave_of_absence — ok（run01，74.0 秒）
- 階段 3 已算分：Completeness 0.6833、Hallucination 0.0；漏斗 [{"id": "K1", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict": "relevant"}, {"id": "K2", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict"
- disagreement：{"keypoint": "K49", "rule": "wrong", "claude": "relevant", "claude_reason": "答案寫註冊組王組長分機 63273", "rule_detail": {}}
- disagreement：{"keypoint": "K51", "rule": "wrong", "claude": "relevant", "claude_reason": "答案寫出納組劉桂芬（組長）分機 62120", "rule_detail": {}}
- disagreement：{"keypoint": "K53", "rule": "wrong", "claude": "relevant", "claude_reason": "答案寫住宿組趙紀綱（組長）分機 62500", "rule_detail": {}}
- disagreement：{"keypoint": "K55", "rule": "wrong", "claude": "relevant", "claude_reason": "答案寫生僑組盧翠婷（組長）分機 63010", "rule_detail": {}}
- disagreement：{"keypoint": "K57", "rule": "wrong", "claude": "relevant", "claude_reason": "答案寫原資中心蔡炎龍（中心主任）分機 62200", "rule_detail": {}}
- 現場讀取：live_changed×7、live_same×5

### Q6 leave_and_library_phone — ok（run01，96.9 秒）
- 階段 3 已算分：Completeness 0.5075、Hallucination 0.0；漏斗 [{"id": "K1", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict": "relevant"}, {"id": "K2", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict"
- disagreement：{"keypoint": "K51", "rule": "wrong", "claude": "relevant", "claude_reason": "答案寫出納組劉桂芬 62120、余淑娟 62123", "rule_detail": {}}
- disagreement：{"keypoint": "K53", "rule": "wrong", "claude": "relevant", "claude_reason": "答案寫住宿組趙紀綱（組長）62500", "rule_detail": {}}

### Q7 master_transfer — ok（run01，41.2 秒）
- 階段 3 已算分：Completeness 0.6897、Hallucination 0.0345；漏斗 [{"id": "K1", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict": "relevant"}, {"id": "K2", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict"
- disagreement：{"keypoint": "K28", "rule": "miss", "claude": "relevant", "claude_reason": "答案寫辦理地點行政大樓 4 樓（教務處註冊組）", "rule_detail": {}}
- 現場讀取：live_changed×1、live_same×2

### Q8 dorm_deposit — error（run01，39.9 秒）
- 出錯，結束碼 1；見 logs/Q08.log

### Q9 master_double_major — error（run01，53.7 秒）
- 出錯，結束碼 1；見 logs/Q09.log

### Q10 overseas_exchange_credit — ok（run01，74.8 秒）
- 階段 3 已算分：Completeness 0.6538、Hallucination 0.0385；漏斗 [{"id": "K1", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict": "relevant"}, {"id": "K2", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict"
- disagreement：{"keypoint": "K23", "rule": "miss", "claude": "relevant", "claude_reason": "答案在通識教育中心那一項寫「教務處（行政大樓 4 樓）」，4 樓一致，但這句沒有證據支持（證據只把 4 樓放在註冊組底下）", "rule_detail": {}}
- 現場讀取：live_changed×5、live_same×5

### Q11 cross_school_double_major — ok（run01，55.0 秒）
- 階段 3 已算分：Completeness 0.3333、Hallucination 0.1905；漏斗 [{"id": "K1", "in_context": false, "in_context_source": "claude", "context_quote": null, "stated_correctly": false, "grounded": false, "verdict": "wrong"}, {"id": "K2", "in_context": false, "in_context_source": "claude", "context_quote": null, "stated_correctly": false, "grounded": false, "verdict":
- 現場讀取：live_changed×1、live_same×1

## live 與轉址觀察（F19）

- 全批現場讀取狀態：live_changed×30、live_same×22
- 走到轉址的頁面：沒有（預期：只有第 1 題與提到出納組的第 8 題可能走到總務處人員頁）
- 渲染（Chromium）次數沒有寫進 prediction；要看見它，請讀 `logs/Qxx.log`（已開 `LIVE_LOG=info`）。
