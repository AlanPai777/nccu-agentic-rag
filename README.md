# NCCU Academic Affairs RAG Assistant

A bilingual (Chinese/English) Q&A system for **National Chengchi University (NCCU)** academic affairs. Students and staff ask natural-language questions about course registration, graduation requirements, leave-of-absence procedures, tuition, dormitories, and more — the system returns grounded answers with cited sources, pulled from 150+ crawled NCCU subdomains.

**Topics covered**: course registration (credit limits, add/drop deadlines, cross-school enrollment) · academic records & graduation requirements · leave of absence, reinstatement, and withdrawal procedures · tuition & fee refund policies · student affairs (scholarships, dormitories, clubs, counseling) · library services · international/exchange student services · general affairs & campus regulations.

Two implementations live in this repo:

| | Agentic RAG | Classic RAG |
|---|---|---|
| Entry point | `agentic_rag.py` | `rag/classic_rag.py` |
| Status | **Production, active development** | Stable, not actively developed |
| Retrieval | LLM-driven tool loop (search/grep/fetch pages, no chunking) | Qdrant dense + FTS5 keyword → RRF fusion |
| Setup | LLM API key only | 3 local services + a 40–60 min index build |
| Data needed | Included in this repo | Included, plus a built Qdrant/FTS5 index |

## Quickstart

The preprocessed corpus ships with this repo — no crawling, no index build, just an LLM API key:

```bash
git clone <repo-url>
cd nccu-academic-rag
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — set LLM_PROVIDER and the matching API key (Ollama cloud or OpenRouter)

python agentic_rag.py "如何辦理休學"
```

Full setup detail (both paths, plus Classic RAG's service requirements) is in [docs/setup.md](docs/setup.md).

## Live check against nccu.edu.tw (Phase J)

The corpus is a snapshot (pages as of 2026-08-19; the office contact directory as of 2026-08-25). With **live mode** on, the pages an answer is actually based on are re-fetched from `nccu.edu.tw`, compared with the snapshot, and each source is shown with the time it was checked and what was found: *unchanged*, *updated*, *taken from the site*, or *site unreachable, database used*. It is a demonstration that the system can look things up right now, not a claim of better answers.

- It is **off unless asked for**: with `LIVE_FETCH` unset the CLI and `curl` never contact the university's servers. The frontend's "查現場" switch (default on) asks for it per question.
- Searching (`search_texts`, `grep_texts`) always reads the database; only reading a page, a form, or an office's staff page checks the site.
- How to run it and what the settings mean: [docs/setup.md](docs/setup.md#path-1c--live-mode-checking-pages-against-nccuedutw). How it works: [docs/architecture.md](docs/architecture.md#live-check-against-nccuedutw-phase-j).

## Documentation

| I want to... | See |
|---|---|
| Get it running | [docs/setup.md](docs/setup.md) |
| Understand how the pipeline works | [docs/architecture.md](docs/architecture.md) |
| Run the SSE API server (connect a frontend) | [docs/setup.md](docs/setup.md#path-1b--run-the-assistant-api-server-for-a-frontend-integration) |
| Turn live checking on, or look at the live UI without any network | [docs/setup.md](docs/setup.md#path-1c--live-mode-checking-pages-against-nccuedutw) |
| Update or expand the crawled corpus | [docs/setup.md](docs/setup.md#path-2--refresh-or-expand-the-corpus) |
| See what is not done yet and the known limitations | [docs/architecture.md](docs/architecture.md#future-work) |
| Run the classic (embedding-based) system | [docs/setup.md](docs/setup.md#classic-rags-services-only-if-running-ragclassic_ragpy), README table above |

## License

MIT
