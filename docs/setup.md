# Setup

This is the operational runbook: environment install, and the two separate
paths — "just run the assistant" (no data prep needed) vs. "I want to
refresh or expand the corpus." For what the system is and how it's
architected, see the main [README](../README.md) and
[architecture.md](architecture.md).

## Path 1 — Just run it (no data prep needed)

The repo ships with preprocessed data already committed — 154 subdomains'
worth of `extracted_texts.jsonl`/`supplementary_map.json` under `output/`
are tracked in git (see `.gitignore`'s explicit un-ignore rules). You do
**not** need to crawl or preprocess anything to run the production system.

```bash
git clone <repo-url>
cd nccu-academic-rag
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Configure an LLM provider:

```bash
cp .env.example .env
# Edit .env — set LLM_PROVIDER and fill in the corresponding key
```

**Option A — Ollama cloud (`gemma4:31b-cloud`, recommended):**
```bash
# Sign in: ollama signin   OR create a key at https://ollama.com/settings/keys
# In .env:  LLM_PROVIDER=ollama  /  OLLAMA_API_KEY=<your key>
python agentic_rag.py "如何辦理休學"
```

**Option B — OpenRouter API:**
```bash
# In .env:  LLM_PROVIDER=openrouter  /  OPENROUTER_API_KEY=<your key>
python agentic_rag.py "如何辦理休學"
```

That's it — no Qdrant, no embedding model, no index build. This is the
path for the production agentic RAG pipeline (`agentic_rag.py`).

## Path 1b — Run the assistant API server (for a frontend integration)

Only needed if you're connecting a browser frontend (e.g. `CourseLangChain-frontend`'s
"政大 AI 助手" page) instead of using the CLI directly. Same environment as Path 1 above —
no extra setup.

```bash
python server.py
# Uvicorn running on http://0.0.0.0:8001
```

Test it directly before wiring up a frontend:

```bash
curl -N "http://localhost:8001/ask?question=如何辦理休學&session_id=test1"
```

You should see a stream of `data: {"type":"status",...}` lines followed by
`data: {"data":"..."}` token chunks, ending in `data: {"data":"SPECIAL_END_TOKEN"}`.

`server.py` allows exactly one browser origin via CORS, set by `ASSISTANT_FRONTEND_ORIGIN`
(**default `http://localhost:3001`**). The frontend is a deliberately different origin from
this server (not a same-origin `/api` proxy setup), so a mismatch means the browser silently
blocks the response even though the server logs `200 OK`; the frontend shows
"連線中斷" / an `EventSource` error. `pnpm dev` serves on port 3000 unless something else
(e.g. a local Langfuse, which also defaults to 3000) holds it, so when the frontend runs on
3000 set the variable explicitly:

```bash
ASSISTANT_FRONTEND_ORIGIN=http://localhost:3000 python server.py
```

If Langfuse is not running, also set `LANGFUSE_TRACING_ENABLED=false`; otherwise the server
keeps retrying span exports and fills the terminal with "Failed to export span batch".

On the frontend side, point `CourseLangChain-frontend/.env`'s `VITE_ASSISTANT_API_BASE`
at this server's address, then `pnpm build` (this value is compiled into the JS bundle,
not read at runtime — changing it after a build requires rebuilding and redeploying).

Multi-turn state (`session_id` → LangGraph `thread_id`) lives in an in-memory
checkpointer — restarting `server.py` loses all active conversations. There is no
persistence across processes; this is a known, deliberate v1 limitation, not a bug.

## Path 1c — Live mode (checking pages against nccu.edu.tw)

Live mode re-fetches the pages an answer is based on from `nccu.edu.tw` and labels every
source with its check time and status (how it works: [architecture.md](architecture.md#live-check-against-nccuedutw-phase-j)). **It sends requests to the
university's servers**, so it is off unless you ask for it.

**Who decides, per question** (`rag/live/config.py::live_enabled`):

| `LIVE_FETCH` | Server `/ask` without `live=` | `/ask?live=on` | `/ask?live=off` | Frontend switch |
|---|---|---|---|---|
| unset or empty (default) | off | on | off | works |
| `on` | on | on | off | works |
| `off`, or any other value | off | **off** | off | greyed out (`GET /config` reports `live_available: false`) |

`LIVE_FETCH=off` is the operator's kill switch: no request from a client can turn live on.
The CLI has `--live on|off` (`python agentic_rag.py "如何辦理休學" --live on`); without it only
the environment variable counts.

```bash
# Frontend decides per question (its switch defaults to on, so the first question checks the site):
ASSISTANT_FRONTEND_ORIGIN=http://localhost:3000 LANGFUSE_TRACING_ENABLED=false python server.py

# Safe look at the UI with real answers and no request to nccu.edu.tw:
LIVE_FETCH=off python server.py

# Print fetch timings, diffs and failures to stderr (what changed on each page, how long each fetch took):
LIVE_LOG=info python server.py
```

A live question normally takes **70–220 seconds**; the first browser-rendered page also starts
Chromium. Pages and forms are kept in a side cache (`rag/live/_cache/`, gitignored; pages for
10 minutes, forms for 1 hour), so asking about the same page again soon is faster and the source
is shown as "checked about N minutes ago". **Staff pages are never read from the cache**: they
are re-fetched on every question (the cache still records them, but nothing reads that copy).
Chromium needs Playwright's browser (`playwright install chromium`).

**Settings** (environment variables, all optional):

| Variable | Default | Meaning |
|---|---|---|
| `LIVE_FETCH` | unset | see table above |
| `LIVE_LOG` | unset | `info` / `debug` prints the `rag.live` logger to stderr |
| `LIVE_SLOW_WARN_SECONDS` | `120,300` | waiting notices are sent to the frontend once each at these seconds, only while no answer text has appeared |
| `LIVE_PREFETCH` | `off` | `on` starts the likely page/form/staff-page fetches in the background before the agent asks (more requests, less waiting; undecided whether to enable by default) |
| `FORM_GATE` | `off` | `on` asks the LLM which detected forms are relevant before fetching them (fewer requests; experimental, see the plan's P3.5) |
| `LIVE_SNAPSHOT_ASOF` | `2026-08-19` | the date shown for database pages |
| `LIVE_STATIC_SIMILARITY_MIN` | `0.5` | a staff page whose plain-HTTP text is less similar than this to the snapshot is re-read with Chromium |
| `LIVE_HOST_INTERVAL`, `LIVE_GLOBAL_CONCURRENCY`, `LIVE_TTL_*` | see `rag/live/config.py` | politeness toward the university's servers and cache lifetimes |

Only `*.nccu.edu.tw` is ever fetched (allowlist, redirects included).

**Looking at the live UI without any network or LLM.** `scripts/replay_sse.py`
is a stand-in for `server.py` that replays one **fictional** run through the real event code
(same endpoints and event shapes, same default port 8001):

```bash
ASSISTANT_FRONTEND_ORIGIN=http://localhost:3000 python scripts/replay_sse.py
#   --speed 5            five times faster        --port N       another port
#   ?live=on | ?live=off the same question with the site checked / answered from the database
#   &scenario=slow       adds the 120 s / 300 s waiting notices;  &scenario=error  ends in an error
```

Every answer it produces starts with a notice that the data is fictional.

## Path 2 — Refresh or expand the corpus

Only needed if you want to update stale data, add a new subdomain, or
reproduce the dataset from scratch. Three steps, each independently
re-runnable:

```bash
# Step 1 — crawl (separate sibling project, not part of this repo)
# See NCCU-Crawler: https://github.com/alanpai/NCCU-Crawler
# Produces raw HTML/PDF under output/<subdomain>/ (not tracked in this repo's git)

# Step 2 — extract text from the crawled raw files
python rag/preprocess_all.py --subdomain aca   # single subdomain
python rag/preprocess_all.py                   # all subdomains
# Writes output/<subdomain>/extracted_texts.jsonl (this is the file agentic_rag.py reads)

# Step 3 — only if you also run Classic RAG (see below), rebuild its chunk/index files
python rag/build_chunks.py                     # -> rag/chunks.jsonl
python rag/classic_rag.py --build-index        # embed + index into Qdrant + FTS5 (~40-60 min)
python rag/classic_rag.py --build-fts          # FTS5 only, fast, no embedding
```

`agentic_rag.py` never needs Step 3 — it reads `extracted_texts.jsonl`
directly via FTS5 (`rag/fts_proto3.db`-style keyword search) and grep, no
vector index involved.

## Classic RAG's services (only if running `rag/classic_rag.py`)

The agentic pipeline (`agentic_rag.py`, production) needs none of this —
skip this section unless you're specifically running the classic
(embedding-based) system, which has been dormant for a while and is kept
around as a stable reference implementation, not active development.

Classic RAG needs 3 services running concurrently, in separate terminals:

| Service | How to start | Port |
|---|---|---|
| Qdrant (vector DB) | `cd ~/qdrant && ./qdrant` | 6333 |
| ipex-llm Ollama (LLM inference) | `cd ~/ollama-ipex-llm-*/ && ./start-ollama.sh` | 11434 |
| Standalone Ollama (embedding) | `OLLAMA_HOST=0.0.0.0:11435 /usr/local/bin/ollama serve` | 11435 |

```bash
./ollama pull qwen2.5:7b
OLLAMA_HOST=localhost:11435 ollama pull embeddinggemma
```

Two separate Ollama instances are required because `embeddinggemma`
(Gemma3 architecture) is incompatible with the ipex-llm SYCL backend, and
embedding + LLM generation can't coexist in 16GB RAM — `keep_alive=0` on
embedding requests unloads `embeddinggemma` before the LLM is needed.

Once running:

```bash
python rag/classic_rag.py --app                 # web UI, http://localhost:7860
python rag/classic_rag.py --query "選課最多可以修幾學分？"
```

## Environment notes

- `pip install torch --index-url https://download.pytorch.org/whl/cpu`
  before `pip install -r requirements.txt` if you don't already have a
  CPU-only torch build — the default PyPI wheel pulls CUDA dependencies
  this project doesn't use.
- `.env` is gitignored — never commit real keys. `.env.example` documents
  every variable, including the currently-unused Langfuse tracing block.
