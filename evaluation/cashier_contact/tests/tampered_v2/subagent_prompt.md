# tampered_v2 第一次執行實際用的子代理提示詞

原樣；兩個路徑換成佔位符。與 `run-eval-question/assets/subagent_prompt_template.md` 相同（`prompt_version: isolated-v2`）。子代理是 general-purpose，只拿 `trace_input.json`。

```
You are doing one step of an evaluation, and the value of your result depends on you using ONLY the single input file named below. Do not read, list, search or open any other file or directory on this machine (no repository, no other folders, no parent directories, no sibling folders). Do not run shell commands other than reading that one file and writing your one output file. If you feel you need other information, do not look for it: use only what is in the file.

INPUT FILE (read it fully): {INPUT_FILE}

OUTPUT FILE (create it, valid JSON, UTF-8, Chinese text kept as is): {OUTPUT_FILE}

What the input file contains: `answer_text` (an answer a Chinese question-answering system gave to a user) and `evidence_items` (the only texts that system saw when it wrote the answer). Its `task`, `output_format` and `output_format.rules` fields describe exactly what to produce, including how to split the answer into claims, how to quote, and when a claim is supported. Follow them to the letter.

Be honest and strict. Judge support using ONLY the evidence items' text, never your own knowledge about the world. `answer_span` and every evidence `quote` must be copied character for character; a program checks both.

Set the top-level "judge" field to {"model": "<your model name if you know it, else 'subagent'>", "prompt_version": "isolated-v2", "note": "isolated trace by a subagent that read only trace_input.json"}.

When finished, reply with: the number of claims, how many are supported and unsupported, and one sentence listing any claim where you were unsure. Do not paste the whole file back.
```
