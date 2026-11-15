# batch05 階段 A 摘要

- 開始：2026-11-15T19:06:53+08:00；live：True；瀏覽器：True；單題上限：600 秒
- 模型：gemma4:31b-cloud；git：5cc6774（系統有未提交修改）（evaluation/ 有未提交修改）

| 題 | 題目 | 狀態 | run | 耗時(秒) | 答案字數 | Accuracy(規則) | ROUGE-L F | Context 句子 P（字串比對，只供比較） |
|---|---|---|---|---|---|---|---|---|
| Q1 | cashier_contact | ok | run06 | 24.20 | 149 | 3/3 | 0.25 | 0.02 |

指標版本 2026-11-15.context-recall-judged：Context 句子 Recall 要等階段 3 由 Claude 判斷「有沒有讀到」才算（階段 A 之後只有字串比對的 Precision）；此版本之前的 Context 數字不能與之後的直接比較。

還沒跑：Q2、Q3、Q4、Q5、Q6、Q7、Q8、Q9、Q10、Q11

下一步：停在這裡等使用者說「開始評測」並同意開子代理（階段 B，一題一題）。
