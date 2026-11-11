# 出納組的隔離回推測試材料

測試「隔離回推」（階段 3 的第一步：判斷者只看答案與證據，不看標準答案，為答案每個主張找依據）能不能抓到答案裡的錯誤。做法是把一份乾淨的答案**故意改壞**，植入已知的錯誤與對照組，再讓新的子代理隔離回推，最後比對它抓到幾個。

這個資料夾放的是**這一題的材料**（資料）。評測程式的單元測試在 `evaluation/tests/`，兩者不要混。

## 結構

```
tests/
├─ README.md
└─ tampered_v1/                   第一次（2026-11-11），原樣保存，不事後整理
   ├─ answer.txt                  改壞的答案
   ├─ expected.json               鑰匙：每個植入錯誤與對照組的預期狀態（ambiguous 標出有爭議的項目）
   ├─ trace_input.json            當時子代理拿到的輸入（證據含來源行，規則是舊格式；v2 起 prepare 已改）
   ├─ subagent_prompt.md          當時的提示詞，以及與第一次（乾淨答案）的差別
   └─ results/run1/trace.json     子代理的輸出（14 個主張）
```

乾淨答案的隔離回推記錄不在這裡，在 `../runs/run01/`：`trace.json`（子代理）與 `trace.manual.json`（當時我手寫的，非隔離，只當對照）。

## 比對

```bash
python evaluation/compare_tests.py evaluation/cashier_contact/tests/tampered_v1            # 預設 run1
python evaluation/compare_tests.py evaluation/cashier_contact/tests/tampered_v1 --run run2
```

離線，不呼叫 LLM。規則：一個項目的 `line` 是答案裡的一整行，落在這一行的主張都屬於它。預期 unsupported 的項目，這一行至少有一個主張被標 unsupported 就算抓到；預期 supported 的（對照組），這一行至少要有一個主張且全部 supported。`ambiguous` 的項目結果不同時列為 REVIEW，不算失敗。結束碼 0＝沒有失敗，1＝有失敗，2＝檔案缺漏。

v1 的記錄結果：植入的 6 個錯誤全部抓到、3 個對照組沒有誤判（`evaluation/tests/test_compare_tests.py` 把這個結果當固定資料測比對邏輯）。**這只是一個子代理、一次執行、一份答案**，不能說下次也會抓到；LLM 每次輸出會不同。

## v2 的記錄結果（2026-11-11）

用新規則（9 條）與剝掉來源行的證據，重做同一份改壞答案：6/6 抓到、3/3 沒誤判，10 個主張、被包含不計入 0 個，逐字驗證 0 警告。主張比 v1 粗（每個人一行一個主張，是規則 7、9 的結果）。T5 在 v2 是 `fabricated`，與 v1 的 `trap` **不可比**。完整記錄在 `tampered_v2/report.md`（一個子代理、一次執行、一份答案）。

## 重做一次隔離回推（做法；v2 已照此做過）

要用子代理，需要使用者同意。腳本 `.claude/skills/isolated-trace-check/scripts/make_tampered_version.py` 做步驟 1。

1. 用 `stage3.py prepare` 為改壞的答案重新產生 `trace_input.json`（這樣才有新規則與剝掉來源行的證據）：把 `answer.txt` 的內容放進一份 `prediction.json` 的 `answer_raw`，其餘沿用乾淨 run 的 `prediction.json`，放在暫存資料夾裡跑 `prepare`；產出的 `trace_input.json` 存到新資料夾 `tampered_v2/`。`answer.txt` 與 `expected.json` 直接複製 v1（v2 的 T5 不再是網址陷阱，`ambiguous` 標記與說明要改）。
2. **只把 `trace_input.json` 單獨複製到一個全新的空資料夾**（絕對不要給子代理 run 資料夾或這個資料夾：裡面有鑰匙、手寫判斷與 gold）。
3. 開一個新的子代理，提示詞用 `subagent_prompt.md` 的模板，把 `{INPUT_FILE}`、`{OUTPUT_FILE}` 換成那個空資料夾裡的路徑。新規則已經寫在 `trace_input.json` 的 `output_format.rules`，不必再手動加。
4. 子代理寫出的 `trace.json` 存到 `tampered_v2/results/run1/`。
5. 跑 `compare_tests.py`，與 v1 對照：新規則有沒有讓拆分更乾淨（沒有重疊、人與分機不拆）、抓到的數量有沒有變化。

## 已知限制

- 子代理有沒有看別的檔案，無法證明；只能從工具呼叫次數與耗時推測它照指示只讀一個檔、寫一個檔。
- v1 的提示詞比第一次多了兩句規則（人與職稱分機要成對、網址裡的字不算證據），所以交叉配對與網址陷阱抓得到，有一部分是規則寫明的功勞。
- v1 的 T5（「負責學雜費退費業務」）在當時的證據裡有來源行網址含「退費」，所以標 `ambiguous`；v2 起這類來源行已從證據剝掉，v2 的 T5 改為 `fabricated`、不再 `ambiguous`，與 v1 不可比。

## 名稱說明

「隔離回推」原稱「盲回推」（2026-11-11 改名）。`tampered_v1/` 底下的 `subagent_prompt.md`、`expected.json`、`trace_input.json` 與 `results/` 是當時原樣保存的記錄，裡面仍寫舊名與舊資料夾名，不改。
