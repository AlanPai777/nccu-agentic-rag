# 盲回推提示詞（tampered_v1 當時實際送給子代理的版本）

這是 2026-11-11 對改壞的答案做盲回推時，交給新的子代理（`general-purpose`）的提示詞。與原文逐字相同，只有兩處檔案路徑改成佔位符：

- `{INPUT_FILE}`：當時是暫存資料夾裡**單獨複製過去**的 `trace_input.json`（資料夾裡沒有別的檔案）
- `{OUTPUT_FILE}`：同一個資料夾裡的 `trace.json`

## 與第一次（乾淨答案，`runs/20261109-234225/trace.json`）的差別

第一次的提示詞少了規則 4 的最後兩句：

- 「Read each claim as a whole: a claim that pairs a person with a title or an extension is supported only if the evidence pairs that same person with that same title and extension.」
- 「A word that merely appears inside a URL or a link address is not evidence for a statement about what an office does.」

所以這一份的交叉配對與網址陷阱能抓到，有一部分功勞是規則寫明了。v2 起這些規則已經寫進 `trace_input.json` 的 `output_format.rules`（`evaluation/stage3.py` 的 `OUTPUT_FORMAT`），而且 `prepare` 會把證據裡的來源行剝掉，提示詞可以縮短成只講檔案路徑與「只讀這一個檔」。

## 提示詞

```
You are doing one step of an evaluation, and the value of your result depends on you using ONLY the single input file named below. Do not read, list, search or open any other file or directory on this machine (no repository, no other folders, no parent directories, no sibling folders). Do not run shell commands other than reading that one file and writing your one output file. If you feel you need other information, do not look for it: use only what is in the file.

INPUT FILE (read it fully): {INPUT_FILE}

OUTPUT FILE (create it, valid JSON, UTF-8, Chinese text kept as is): {OUTPUT_FILE}

What the input file contains: `answer_text` (an answer a Chinese question-answering system gave to a user) and `evidence_items` (the only texts that system saw when it wrote the answer). Its `task`, `output_format` and `output_format.rules` fields describe exactly what to produce.

Your task: split `answer_text` into atomic factual claims (one claim = one fact; for example a switchboard number and an extension written on the same line are two claims, a fax number is another). For each claim, decide whether the evidence items support it, and if so quote the supporting text from the evidence. Greetings, headings and phrases like "as follows" that carry no fact are not claims; do not list them.

Strict rules:
1. `answer_span` must be copied character for character from `answer_text` (a contiguous piece of it, as short as possible while naming the claim). A program will check that it is an exact substring.
2. Each evidence `quote` must be copied character for character from the `text` of the evidence item you name in `item`. A program will check it. Do not rephrase, fix spacing, or normalise anything inside a quote.
3. `status` is "supported" only if the quoted evidence really says what the claim says; otherwise "unsupported" with `evidence` as an empty list. Judge support using ONLY the evidence items' text, never your own knowledge about the world.
4. Be honest and strict. A claim whose numbers, names or titles are not in the evidence, or are different from what the evidence says, is "unsupported". Read each claim as a whole: a claim that pairs a person with a title or an extension is supported only if the evidence pairs that same person with that same title and extension. A claim that is only partly in the evidence should be judged on what the evidence actually says, and explained in `why`. A word that merely appears inside a URL or a link address is not evidence for a statement about what an office does.
5. Each claim has: id ("c1", "c2", ...), answer_span, status, evidence (list of {item, quote}), why (one short sentence).
6. Top level of the output: {"claims": [...], "judge": {"model": "<your model name if you know it, else 'subagent'>", "prompt_version": "blind-v1", "note": "blind trace by a subagent that read only trace_input.json"}}

When finished, reply with: the number of claims, how many are supported and unsupported, and one sentence listing any claim where you were unsure. Do not paste the whole file back.
```
