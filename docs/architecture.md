# Architecture

Current-state reference for the agentic RAG pipeline — what exists today
and how it fits together. For setup/running instructions see
[setup.md](setup.md); for the classic (embedding-based) system, see the
[README](../README.md)'s Classic RAG section.

This is a distilled view. The full design rationale — every decision,
alternative considered, and the spike scripts that proved or disproved
each one — lives in `docs/phase_h_agentic_rag_migration_plan.md` and the
earlier `docs/phase_g_*` research documents. Those are written for
picking a project back up mid-thought across sessions, not for a reader
who just wants to know what the system does today — read this file
instead unless you specifically need the "why."

## Overview

`agentic_rag.py` (repo root) is the production entry point — a single
LLM tool-loop over the crawled NCCU academic-affairs corpus, replacing an
earlier multi-skill LangGraph pipeline (Phase E, deleted). Query
classification is a logging label, not a routing decision for most
queries; RESOURCE (form lookup) and CONTACT (office lookup) are the only
genuine early-exit routes, and even those loop back into the main tool
loop afterward so the agent can decide if more work is needed.

## Pipeline

```
Query
  │
  ▼
plan_node — rag/router.py's 2-layer classifier (keyword → LLM fallback).
             4-way split: compound / resource / contact / knowledge.
             PROCEDURE is a label only (logging/self_eval) — it folds
             into "knowledge" here, not a separate graph route.
  │
  ├─(compound)──▶ multi_sub_query_node ──▶ synthesis_node
  │               (splits on 逗號/句號; each sub-query runs its own nested
  │                inner-loop, sequential v1 — not Send-parallel)
  │
  ├─(resource)────────────────┐
  ├─(contact)───────────────┐ │
  │                          │ │        ┌── ALSO reachable mid-loop, marker-
  │                          │ │        │   triggered from tool output:
  │                          ▼ ▼        │   [偵測到表單編號] / [偵測到辦公室]
  │                    resource_node ───┼──▶ contact_node
  │                          │          │        ▲
  │                          └──────────┴────────┘
  │                                     │
  │                    (both always funnel back into rewrite_node below —
  │                     even a pure RESOURCE/CONTACT query re-enters the
  │                     loop afterward so the agent can decide if more
  │                     work is needed, or finish)
  │                                     │
  └─(knowledge/procedure)───────────────┤
                                         ▼
                        ┌─────────────────────────────┐
                        │ rewrite_node (LLM)          │
                        │      ↓                       │
                        │ domain_router_node (turn 1) │
                        │      ↓                       │
                        │ agent_node (ChatOllama      │
                        │   .bind_tools(), 5 tools)   │
                        │      ↓                       │
                        │ tools (ToolNode: search_texts│
                        │  /grep_texts/get_page/       │
                        │  extract_links/get_form)     │
                        │      ↓                       │
                        │ loop back to rewrite_node,   │
                        │ OR marker exit up to         │
                        │ resource_node/contact_node   │
                        │ above                        │
                        └──────────────┬───────────────┘
                            agent decides "done"
                                       ▼
                               synthesis_node ◀──────────────╮
                                       │                       │
                               self_eval_node ──(retry, no    │
                                       │          hard cap)───╯
                                      END
```

**Notable design choices:**
- **RESOURCE/CONTACT are first-class routes from `plan_node`, not just mid-loop side effects.** A query classified RESOURCE/CONTACT skips the initial tool-loop pass entirely and goes straight to `resource_node`/`contact_node` — the same two nodes also reachable mid-loop via deterministic marker detection on tool output, and chained (resource → contact) when a fetched form's own text mentions an office. All three entry paths funnel back into the loop afterward.
- **No hardcoded office/form lists.** Office detection (`_detect_offices()`) and form extraction work against whatever the retrieved content actually contains, not a fixed list tied to one procedure (e.g. leave-of-absence).
- **`self_eval_node` runs on every path**, including ones routed directly — a smooth routing path doesn't guarantee a correct answer. Two-stage: a free deterministic checklist gate first, LLM judgment only if that passes. No hard retry cap, just a generous turn-count ceiling as a safety net.
- **No parametric fallback.** If retrieval genuinely finds nothing, the system says so — it does not answer from the LLM's own training knowledge. NCCU-specific institutional detail (which office handles what, current phone extensions, form IDs) is exactly the kind of long-tail fact no LLM's training data reliably has right.

## Assistant API server

`server.py` (repo root) wraps the graph above in a FastAPI SSE service for
`CourseLangChain-frontend`'s "政大 AI 助手" page — the pipeline described so
far is otherwise unchanged, this is purely a serving layer. Full design
rationale and implementation findings (including two real bugs found and
fixed during rollout) are in `docs/phase_i_assistant_api_design.md`; this
section is the distilled current-state summary.

- **Streaming**: `graph.astream(..., stream_mode=["updates","messages","custom"])` (`"custom"` carries the live-check progress events, see the next section).
  The `"messages"` stream is filtered to
  `isinstance(chunk, AIMessageChunk) and metadata["langgraph_node"]=="synthesis_node"`
  — both conditions matter. `langgraph_node` alone isn't enough because
  `stream_mode="messages"` surfaces *any* message added to `state["messages"]`
  by a node's return value, not just live token deltas; `synthesis_node`
  also appends its answer to `messages` (see below), so without the
  `isinstance` check the answer streamed twice — once as genuine deltas,
  once whole as that appended message.
- **Session memory**: `build_graph(checkpointer=InMemorySaver())` — `server.py`'s
  only caller that passes a real checkpointer (the CLI's `run()` doesn't).
  `session_id` maps directly to the LangGraph `thread_id`. In-memory only —
  no persistence across process restarts.
- **Cross-turn compaction**: `synthesis_node` appends its answer to
  `messages` as a plain `AIMessage` (not just `state["answer"]`, which no
  node reads and which every new turn resets to `None`) so the conclusion
  survives into the next turn. Before a new turn starts on an existing
  `thread_id`, `rag/agentic/compaction.py`'s `compact_previous_turn()`
  collapses the *entire* previous turn's `messages` (candidate lists,
  fetched pages, form/office text) down to just
  `[HumanMessage(prev_query), AIMessage(prev_answer)]` via LangGraph's
  `RemoveMessage` — otherwise `synthesis_node`'s un-scoped
  `_render_full_messages()` would leak a prior unrelated topic's fetched
  content into a new turn's synthesis prompt.
- **Status side channel**: `{"type":"status",...}` events reuse text nodes
  already generate for their own purposes (`rewrite_node`'s `rewritten`,
  `domain_router_node`/`self_eval_node`'s injected messages) rather than a
  dedicated summarizer call. `self_eval_node`'s retry signal
  (`{"type":"reset"}`, telling the frontend to file a rejected draft into
  its thinking-log instead of concatenating it with the replacement answer)
  keys off `self_eval_note` being set — one of self_eval's three failure
  branches (情況B) never populates `messages`, so that field is the signal
  common to all three — **and** (2026-09-03 fix) `server.py`'s own tracked
  `state["turn"]` still being below `self_eval_node`'s `_SELF_EVAL_MAX_TURN`
  ceiling. That second condition matters: on the ceiling turn,
  `self_eval_node` can still reject (`self_eval_note` truthy), but
  `_after_self_eval` routes to `"end"` instead of back for another
  synthesis pass, so no replacement answer is ever coming. Without this
  guard, that terminal rejection fired `reset` anyway, wiping the
  already-streamed (often correct) final answer and leaving the frontend
  blank with "已停止生成" even though the backend had produced a good
  answer — full investigation trail in `debug.md` (repo root, untracked).

## Live check against nccu.edu.tw (Phase J)

The corpus is a snapshot. With live mode on, the pages an answer is based on are re-fetched
from `nccu.edu.tw`, compared with the snapshot, and every source is reported with a check time
and a status. Design record, measurements and every decision: `docs/phase_j_live_fetch_plan.md`;
this section is the distilled current state. The graph above is unchanged: live checking is a
layer under the tools and the two routed nodes, so the agent still just calls `get_page`.

```
get_page_tool ─────────┐
extract_links_tool ────┼─▶ hook.apply_page ──┐
get_form_tool ─────────┤                      │          allowlist (*.nccu.edu.tw, redirects too)
resource_node ─────────┴─▶ hook.apply_form ──┤          per-host rate limit, retry, circuit breaker
contact_node ──▶ contacts.fetch_contact_pages ┤          side cache rag/live/_cache (TTL by kind; staff pages are written, never read)
                                              ▼
                              Fetcher (httpx) ── static text too different, or no contacts parsed ──▶ Chromium
                                              │                       (one browser-owner thread, same extractor)
                                              ▼
                          compare.normalize/compare  (counters and volatile lines removed)
                          resolve: same → snapshot text · changed → live text · failed → snapshot + disclosure
                                              │
                         ledger marker  [live:src status=… checked=… snap=… url=…]  in the tool output header
                                              │
                       ┌──────────────────────┴───────────────────────┐
         synthesis_node appends 【資料狀態】 footer          server.py: build_sources() → `sources` event
         (state["answer"] keeps it; not streamed)            (grouped by site, only pages the model really read)
```

- **Searching never touches the site.** `search_texts` and `grep_texts` read the database and only find candidates; reading a page (`get_page`), a form, or an office's staff page is what checks the site. A search row labelled "使用資料庫" is therefore correct. A question the agent answers from search snippets alone, without reading a page, has no checked content.
- **Per-question choice.** `AgentState.live` (`True` / `False` / `None`) is set from `/ask?live=on|off` or the CLI's `--live`, and the tools read it with `InjectedState`. `rag/live/config.py::live_enabled` combines it with `LIVE_FETCH` (see [setup.md](setup.md#path-1c--live-mode-checking-pages-against-nccuedutw)). `None` leaves every output byte-identical to the pre-live system; an explicit `False` makes the tools write a `snapshot` marker so the sources list still shows the database pages that were read.
- **Ledger.** The marker lines are the single source of truth: the footer and the `sources` event are both built from them with `ledger.parse_markers`, which only trusts the headers of tool messages (page text is sanitized, so a page cannot forge a marker). User-facing wording lives in `ledger.py` (`_LABEL`, `_SHORT_LABEL`): 已與官網核對，內容無變動 · 已與官網核對，內容已更新 · 從官網取得 · 未能連上官網，使用資料庫（8/19） · 此頁需瀏覽器顯示，未能核對，使用資料庫（8/19） · 官網顯示此表單已停用 · 使用內建的固定聯絡資料（非官網頁面） · 使用資料庫（8/19）.
- **One extractor.** Live HTML goes through the same `rag/preprocess.py::extract_html_bytes` as the corpus, so differences between live and snapshot are meant to be real changes. Known exceptions are recorded in the plan (a contact-index snapshot whose page structure differed from today's; staff emails that a site writes with JavaScript are decoded by `_decode_script_emails_in_soup`).
- **Progress events** (`"custom"` stream, `rag/live/events.py`): `{"type":"step","kind":"group",…}` opens one block per tool action (`search`, `grep`, `page`, `links`, `form`, `contacts`), `{"type":"step","kind":"row",…}` adds or updates a page row inside it (pending → done, with state, label, check time, cached age). Worker threads must be started with `events.submit_with_context` (a copy of the node's context), otherwise the stream writer fails while streaming and succeeds silently under `invoke`.
- **Server additions** (`server.py`): `GET /config` (`live_available`, `snapshot_date`), `/ask?live=on|off`, a `meta` event at the start, `slow` notices (120 s / 300 s, once each, only before answer text appears), and a `sources` event sent after the graph ends, so a `self_eval` retry cannot leave a stale list. The status side channel now says only what the action blocks cannot (question type, narrowed site, what a page mentioned).
- **Frontend** (`CourseLangChain-frontend`, `useChat.ts`, `ProgressList.vue`, `SourcesModal.vue`, `LiveSwitch.vue`): a collapsible timeline of notes and action blocks, a sources pill and modal grouped by site, the "查現場" switch, the waiting notice.
- **Parent units** (`rag/agentic/logic/parent_offices.py`, plan P6.5): a unit whose index page is a site's home page (教務處, 學生事務處) has no staff there, so `contact_node` reads its sibling staff pages instead, in `docs/contact.csv` order, three at a time (`PARENT_BATCH_SIZE`, the user's choice), stopping at the first batch with parsed contacts; the parent's own page and then `KNOWN_CONTACTS` come last. This happens only when the parent is named in the user's question: on the direct CONTACT route the question is scanned on every turn, and a parent that appears only in page text is skipped. Stray spaces inside a unit name are removed (between Chinese characters only) before the detector's substring checks. Checked against the real site for 教務處 and 學生事務處 (single sample); multi-turn, compound questions and other hosts are not verified.
- **Not done**: a "waiting" row state for pages queued behind the same host's rate limit (they show "讀取中…"), a marker for `extract_links` (it goes through `apply_page` but writes no ledger line), model-written narration of the steps (the lines are assembled by code).

### Politeness toward the university servers

- **Where requests may go.** Only `nccu.edu.tw` and its subdomains. Anything else is refused before a request is made.
- **Identity.** The httpx requests send the same User-Agent string as the earlier crawler that built the corpus, an "academic research bot". The URL inside it points at the university home page, so the string does not say how to reach this project. Playwright keeps Chromium's own default user agent.
- **Pace.** Each host allows one new request per second and two in flight, and the whole process allows four in flight. `osa.nccu.edu.tw` is limited to one request every 10 seconds, one at a time, because its robots.txt asks for `Crawl-delay: 10`. `moltke` and `cpbae` have their own settings. All of it is in `rag/live/config.py` and can be changed with environment variables.
- **Failures.** A request that times out, or a host that fails several times in a row, only affects its own pages. Those pages fall back to the snapshot and are marked as a fallback in the answer.
- **Certificates.** Verification is turned off for one host only, `cashier.nccu.edu.tw`, and every such page is flagged so the answer can say it.

### Known limitations

- `aff.nccu.edu.tw` and `mend.nccu.edu.tw` do not send an intermediate certificate, like `cashier`, but they are not on the exception list. Their pages show as unreachable.
- robots.txt is not read while running. The 10-second pace for `osa` is written into the settings by hand, and other hosts' robots.txt files have not been checked.
- A page that is fetched but yields no people is not reported as such to the user.
- The failure message "未能連上官網" is shown for every failed fetch, including a 404 or an empty page.
- Contact lists are limited to a few people per office in the final answer, even when the page lists many more.

## Key modules

| Module | Role |
|---|---|
| `agentic_rag.py` | Graph assembly + CLI (`build_graph(checkpointer=None)`/`initial_state()`/`--subdomain`/`--stream`/`--no-eval`) |
| `server.py` | FastAPI SSE server for `CourseLangChain-frontend` — see "Assistant API server" above |
| `rag/agentic/compaction.py` | `compact_previous_turn()` — cross-turn `messages` compaction via `RemoveMessage`, called by `server.py` |
| `rag/agentic/nodes/` | Graph-node wrappers: `plan.py`, `loop.py` (rewrite/domain_router/agent), `resource.py`, `contact.py`, `synthesis.py`, `compound.py`, `self_eval.py` |
| `rag/agentic/logic/` | Pure functions behind the nodes — office/form detection, rewrite, self-eval checks — testable without any graph state |
| `rag/agentic/tools/` | The 5 tools the agent can call: `search_texts` (FTS5 + LLM-judge), `grep_texts`, `get_page`, `extract_links`, `get_form` |
| `rag/router.py` | 2-layer query classifier (keyword → LLM fallback), reused by `plan_node` |
| `rag/agent_tools.py` | Retrieval primitives reading from `output/<subdomain>/extracted_*.jsonl` |
| `rag/llm_client.py` | Ollama cloud / OpenRouter client |
| `rag/eval.py` | 13-criteria / 26-point scoring used in regression testing |
| `rag/skills/office_lookup_skill.py` | Office-contact lookup against `output/office_contacts_index.jsonl`; regex-parses labeled/tabular page layouts first, falls back to an LLM extraction pass (`_llm_extract_contacts()`) over the whole page when the regex layer can't find an explicit name label (2026-09-03 fix — see `debug.md`) |
| `rag/live/` | Live check against nccu.edu.tw: `hook.py` (`apply_page`/`apply_form`), `fetcher.py`, `browser.py` (Chromium owner thread), `contacts.py`, `forms.py`, `compare.py`, `resolve.py`, `ledger.py` (markers, footer), `sources.py`, `events.py`, `site_names.py`, `config.py` |
| `rag/classic_rag.py` | Separate, stable classic (embedding-based) RAG system — not part of this pipeline, see README |

## Project structure

```
agentic_rag.py               # production entry point (repo root)
server.py                    # FastAPI SSE server for CourseLangChain-frontend (Phase I)

rag/
├── classic_rag.py            # Classic RAG CLI entry point (stable, separate system)
├── router.py                 # 2-layer query classifier, shared by plan_node
├── domain_router.py          # Layer 1/2/3 subdomain routing (keyword table / FTS5 count / global fallback)
├── agent_tools.py            # Retrieval primitives: grep_texts, get_page, extract_links, get_form
├── llm_client.py             # Ollama cloud + OpenRouter client
├── eval.py                   # 13-criteria / 26-point regression scoring
├── preprocess.py             # HTML/PDF -> extracted_texts.jsonl (single record)
├── preprocess_all.py         # Batch extraction driver (all/one subdomain)
├── keyword_store.py          # SQLite-FTS5 + jieba BM25 (shared by search_texts and Classic RAG)
├── agentic_main.py           # Research/prototype pipeline predating the migration -- not production
├── proto1_direct.py          # Older baseline agent loop (Mode 1/2/3), reference only
│
├── analyze_links.py          # One-off: discover supplementary link sources in a crawled subdomain
├── fetch_moltke_forms.py     # One-off: download form PDFs from moltke.nccu.edu.tw
├── fetch_supplementary.py    # One-off: download direct-URL supplementary files
├── fetch_office_contacts.py  # One-off: Playwright re-crawl of docs/FindURLs/contact.csv -> office_contacts_index.jsonl
├── supplementary_map.py      # Shared helper: read/write output/<subdomain>/supplementary_map.json
├── export_for_llm.py         # One-off: merge extracted_texts.jsonl files for manual web-LLM testing
│
├── agentic/                  # Agentic RAG's package (imported by ../agentic_rag.py)
│   ├── state.py                  # AgentState TypedDict
│   ├── compaction.py             # compact_previous_turn() -- server.py's cross-turn RemoveMessage compaction
│   ├── nodes/                    # Graph-node wrappers
│   │   ├── plan.py                   plan_node, _after_plan
│   │   ├── loop.py                   rewrite_node, domain_router_node, agent_node, tool routing
│   │   ├── resource.py               resource_node
│   │   ├── contact.py                contact_node
│   │   ├── synthesis.py              synthesis_node
│   │   ├── compound.py               multi_sub_query_node
│   │   └── self_eval.py              self_eval_node
│   ├── logic/                    # Pure functions behind the nodes (no graph state)
│   │   ├── office_detection.py
│   │   ├── form_extraction.py
│   │   ├── rewrite.py
│   │   └── self_eval_checks.py
│   └── tools/                    # The 5 @tool functions exposed to the agent
│       ├── search.py                 search_texts
│       ├── grep.py                   grep_texts_tool
│       ├── page.py                   get_page_tool, extract_links_tool
│       └── form.py                   get_form_tool
│
├── live/                     # Phase J: live check against nccu.edu.tw (see the section above)
│
├── skills/
│   ├── office_lookup_skill.py    # Dynamic office-contact lookup (output/office_contacts_index.jsonl)
│   └── procedure_skill.py        # Retained, no remaining callers post-migration
│
└── (classic RAG only, dormant) retriever.py / generator.py / pipeline.py / cache.py /
    embedder.py / indexer.py / build_chunks.py / chunker.py / app.py

output/
└── <subdomain>/
    ├── extracted_texts.jsonl          # tracked in git -- what agentic_rag.py actually reads
    ├── extracted_supplementary.jsonl  # tracked in git, where present -- moltke/newdoc form content
    └── supplementary_map.json         # tracked in git -- form ID -> URL/metadata index
output/office_contacts_index.jsonl     # tracked in git -- Playwright-extracted office directory
```

## Dataset coverage

Verified 2026-09-02 via `git ls-files output/` and a line count of each `extracted_texts.jsonl` (one line = one page/record). Numbers here will drift as the corpus grows — re-run those commands rather than trusting this table indefinitely.

- **154 subdomains** tracked in git, **203,510 records** total.
- The corpus is much broader than the handful of central administrative offices this project's eval suite and prompt engineering actually target — it also includes dozens of individual college/department subdomains (their own announcements, course listings, etc.), several of which are larger by page count than any central office.

**Largest subdomains by record count** (subdomain codes are NCCU's own; most of the ones below are individual colleges/departments — office-name translations are only given for the ones independently documented elsewhere in this project, to avoid guessing at unfamiliar unit names):

| Subdomain | Records | |
|---|---|---|
| `commerce` | 26,289 | |
| `ba` | 12,996 | |
| `osa` | 10,417 | ← core office (Student Affairs / 學務處) |
| `ord` | 9,451 | |
| `aca` | 6,590 | ← core office (Academic Affairs / 教務處) |
| `learning` | 5,335 | ← core office (Teaching & Learning Center) |
| `rmi` | 4,935 | |
| `outgoing-iep` | 4,913 | |
| `stat` | 4,817 | |
| `mis2` | 4,772 | |
| `law` | 4,662 | |
| `finance` | 4,497 | |
| `mba` | 4,296 | |
| `tiipm` | 4,270 | |
| `ib` | 3,844 | |
| `flc` | 2,944 | |
| `mepa` | 2,743 | |
| `history` | 2,589 | |
| `labor` | 2,532 | |
| `banking` | 2,382 | |

**Other core offices** — smaller by volume, but central to the leave-of-absence and related administrative procedures this system was originally built and evaluated around:

| Subdomain | Office | Records |
|---|---|---|
| `www.lib` | Library / 圖書館 (main site; 25+ library sub-subdomains also crawled, e.g. `archive.lib`, `nccur.lib`) | 460 |
| `oic` | International Cooperation / 國合處 | 360 |
| `cashier` | Cashier / 出納組 | 99 |

The 23 subdomains named above (20 by volume + these 3 core offices) are the ones this project's own documentation and eval suite reference by name. The remaining **131 subdomains** (154 total − 23 named) are smaller, long-tail college/department/unit sites not individually described anywhere in this project's docs — run `git ls-files output/*/extracted_texts.jsonl` for the full list.

Supplementary PDFs (official forms from moltke.nccu.edu.tw and newdoc.nccu.edu.tw) are indexed separately per subdomain in `supplementary_map.json` — `get_form()` reads these, not `extracted_texts.jsonl`.

> Some subdomains under `nccuga` and similar administrative groups render content via JavaScript and were largely unextractable via static crawling; this was investigated in `docs/phase_f_planning_report.md` and found to affect only a small number of true positives (`x`/`cpbae`/`gcit`), not the broader `nccuga` group as originally suspected.

## Current status

**Eval**: 26/26 on the flagship "如何辦理休學" (leave-of-absence procedure) query, stable across the current regression suite (compound queries, contact lookups, form-download queries, and previously-unstable factual queries all pass).

**Known limitations**:
- **KNOWLEDGE-path stability isn't proven, only mitigated.** Occasionally the model doesn't call the tools a factual query needs. There's no silent-wrong-answer fallback for this anymore — a failure now surfaces as an honest "not found" — but the underlying non-determinism (LLM sampling variance, not a code bug) hasn't been eliminated, just reduced through tool-scoping, de-duplication, and few-shot examples.
- **`$\rightarrow$` sometimes appears instead of `→`** in generated answers (LaTeX-style arrow from the model). Cosmetic, both forms are accounted for in scoring.
- **Cross-page data inconsistencies exist in the underlying corpus** — e.g. the same office's phone extension differs between two crawled pages. The system reports what each source actually says rather than picking one arbitrarily, which is correct behavior, but surfaces the corpus's own inconsistency to the user.

## Future work

Items with a clear direction but not yet started. Full context for each is in `docs/phase_h_agentic_rag_migration_plan.md` and `docs/phase_g_clean_pipeline_design.md`.

- **Split `rag/agentic/` out of the `rag/` package.** Right now `agentic_rag.py` sits at repo root but still imports from `rag.agentic.*`, and `rag/` also holds shared utilities (`agent_tools.py`, `router.py`, `llm_client.py`, `eval.py`, etc.) that both the agentic and classic systems depend on. A cleaner split — agentic-specific code fully out of `rag/`, shared utilities in their own package — is deferred until there's enough shared-code growth to justify the ~15-file import rewrite.
- **Parallelize compound-query handling.** `multi_sub_query_node` currently processes sub-queries sequentially (v1); a `Send`-based parallel version is a known, scoped upgrade, not yet done.
- **Human-in-the-loop steering.** Letting a user redirect the agent mid-query (e.g. "no, I meant the other office") via LangGraph's `interrupt()` + a checkpointer is an open research thread, not yet prototyped.
- **Broader office-detection coverage.** Office detection currently works against whatever's in retrieved content, but hasn't been stress-tested against the full 150+ subdomain office catalog beyond the cases already in the regression suite.
- **Answer-type-aware search judging.** The search tool's relevance judge currently checks topic match, not whether a candidate page's content actually contains the type of answer being asked for (a number, a name, a date). This is a known gap behind some of the harder factual-query failures.
