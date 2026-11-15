# batch06 階段 A 摘要

- 開始：2026-11-15T19:18:48+08:00；live：True；瀏覽器：True；單題上限：600 秒
- 模型：gemma4:31b-cloud；git：dde1c24（evaluation/ 有未提交修改）

| 題 | 題目 | 狀態 | run | 耗時(秒) | 答案字數 | Accuracy(規則) | ROUGE-L F | Context 句子 P（字串比對，只供比較） |
|---|---|---|---|---|---|---|---|---|
| Q2 | course_limit | ok | run01 | 61.30 | 949 | 5/5 | 0.25 | 0.02 |
| Q3 | leave_form_download | ok | run01 | 68.30 | 1411 | 2/2 | 0.14 | 0.00 |
| Q4 | resumption | ok | run01 | 83.30 | 1136 | 7/9 | 0.28 | 0.01 |
| Q5 | leave_of_absence | ok | run01 | 74.00 | 1997 | 10/16 | 0.20 | 0.03 |
| Q6 | leave_and_library_phone | ok | run01 | 96.90 | 1439 | 14/23 | 0.25 | 0.10 |
| Q7 | master_transfer | ok | run01 | 41.20 | 1015 | 2/5 | 0.22 | 0.09 |
| Q8 | dorm_deposit | error | run01 | 39.90 | - | - | - | - |
| Q9 | master_double_major | error | run01 | 53.70 | - | - | - | - |
| Q10 | overseas_exchange_credit | ok | run01 | 74.80 | 1122 | 5/9 | 0.23 | 0.02 |
| Q11 | cross_school_double_major | ok | run01 | 55.00 | 878 | 2/4 | 0.16 | 0.00 |

指標版本 2026-11-15.context-recall-judged：Context 句子 Recall 要等階段 3 由 Claude 判斷「有沒有讀到」才算（階段 A 之後只有字串比對的 Precision）；此版本之前的 Context 數字不能與之後的直接比較。

## 需要你看的

- Q8 dorm_deposit：error
- Q9 master_double_major：error

還沒跑：Q1

下一步：停在這裡等使用者說「開始評測」並同意開子代理（階段 B，一題一題）。
