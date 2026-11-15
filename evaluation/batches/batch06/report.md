# batch06 跨題報告

- live：True；瀏覽器：True；模型：gemma4:31b-cloud；git：dde1c24；建立：2026-11-15T19:18:48+08:00
- 指標版本：2026-11-15.excluded-keypoints（Context 句子 Recall 由 Claude 判斷，不是字串比對；Sentence Precision 與 Words 指標仍是字串比對，Sentence F1 混合；此版本之前的 Context 數字不能直接比較）
- 限制：每題只跑一次，LLM 有隨機性；現場頁面會隨時間變，`prediction.json` 是系統當時看到的唯一記錄；隔離回推是否真的隔離看每題 `trace.json` 的 judge 註記與稽核結果。

- 重跑（2026-11-15，F35（表單快取種類）、F36（下載連結行）、F37（雙查詢搜尋） 修好之後，git 7dd5427）：Q7、Q8、Q9、Q11 改用 run02，Q10 與其他題仍是第一次的 run01；四題的 run01 都保留；批次用的 11 個 run 都以 2026-11-15.excluded-keypoints 重算（只有 Q7 的數字因排除 K10、K11 而改變）

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

### Q7 master_transfer — ok（run02，34.0 秒）
- 重跑（2026-11-15，F35–F37 修好後，git 7dd5427）：重跑以驗證 F36（下載連結行）；第一次 run01 的 K25 連結用了資管系的 PDF；run01 保留；K10、K11 不計分（議題 F39，gold 標 excluded）：答案把申請期間寫成生效學期的說法，與官方字面不同、現實中很可能相符；run02 的分數用 2026-11-15.excluded-keypoints 版（Completeness 0.63、Hallucination 0），run01 仍是舊版、K10、K11 照常計分
- 階段 3 已算分：Completeness 0.6296、Hallucination 0.0；漏斗 [{"id": "K1", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict": "relevant"}, {"id": "K2", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict"
- 不計分：K10（F39，gold 沒說明「上學期／下學期」是申請所在的學期還是生效學期，答案兩種說法都可能；先不計分；判 wrong）
- 不計分：K11（F39，gold 沒說明「上學期／下學期」是申請所在的學期還是生效學期，答案兩種說法都可能；先不計分；判 wrong）
- 現場讀取：live_changed×2、live_same×2

### Q8 dorm_deposit — ok（run02，53.3 秒）
- 重跑（2026-11-15，F35–F37 修好後，git 7dd5427）：第一次 run01 因 F35（表單快取種類混用）出錯，修好後重跑；run01 保留
- 階段 3 已算分：Completeness 0.7826、Hallucination 0.0；漏斗 [{"id": "K1", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict": "relevant"}, {"id": "K2", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict"
- disagreement：{"keypoint": "K21", "rule": "wrong", "claude": "relevant", "claude_reason": "答案列出住宿組趙紀綱（組長）分機 62500、徐廷芝分機 62228，都在允許集合內", "rule_detail": {}}
- disagreement：{"keypoint": "K23", "rule": "miss", "claude": "relevant", "claude_reason": "答案寫出納組在行政大樓 5 樓", "rule_detail": {}}
- 現場讀取：live_changed×2、live_same×2

### Q9 master_double_major — ok（run02，45.6 秒）
- 重跑（2026-11-15，F35–F37 修好後，git 7dd5427）：第一次 run01 因 F35（表單快取種類混用）出錯，修好後重跑；run01 保留
- 階段 3 已算分：Completeness 0.7391、Hallucination 0.0；漏斗 [{"id": "K1", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict": "relevant"}, {"id": "K2", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict"
- disagreement：{"keypoint": "K23", "rule": "miss", "claude": "relevant", "claude_reason": "答案寫註冊組在行政大樓 4 樓", "rule_detail": {}}
- 現場讀取：live_changed×2、live_same×1

### Q10 overseas_exchange_credit — ok（run01，74.8 秒）
- 階段 3 已算分：Completeness 0.6538、Hallucination 0.0385；漏斗 [{"id": "K1", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict": "relevant"}, {"id": "K2", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict"
- disagreement：{"keypoint": "K23", "rule": "miss", "claude": "relevant", "claude_reason": "答案在通識教育中心那一項寫「教務處（行政大樓 4 樓）」，4 樓一致，但這句沒有證據支持（證據只把 4 樓放在註冊組底下）", "rule_detail": {}}
- 現場讀取：live_changed×5、live_same×5

### Q11 cross_school_double_major — ok（run02，39.9 秒）
- 重跑（2026-11-15，F35–F37 修好後，git 7dd5427）：重跑以驗證 F37（改寫後再用原問題搜尋）；第一次 run01 找錯頁面（Completeness 0.33）；run01 保留
- 階段 3 已算分：Completeness 0.6667、Hallucination 0.0；漏斗 [{"id": "K1", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict": "relevant"}, {"id": "K2", "in_context": true, "in_context_source": "inferred", "context_quote": null, "stated_correctly": true, "grounded": true, "verdict"
- disagreement：{"keypoint": "K21", "rule": "miss", "claude": "relevant", "claude_reason": "答案寫註冊組在行政大樓 4 樓", "rule_detail": {}}
- 現場讀取：live_changed×2、live_same×1

## live 與轉址觀察（F19）

- 全批現場讀取狀態：live_changed×36、live_same×25
- 走到轉址的頁面：沒有（預期：只有第 1 題與提到出納組的第 8 題可能走到總務處人員頁）
- 渲染（Chromium）次數沒有寫進 prediction；要看見它，請讀 `logs/Qxx.log`（已開 `LIVE_LOG=info`）。
