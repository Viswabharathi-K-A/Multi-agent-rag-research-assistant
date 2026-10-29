# Multi-Agent RAG Research Assistant

A document-grounded research and coding assistant for distributed systems papers.
An LLM supervisor delegates work to Research, Code, and Summary agents through
LangGraph. A React interface displays streamed output, routing decisions,
execution traces, source excerpts, and the final answer.

Built as a graduate course project and developed into a local portfolio application.

## What it does

- Retrieves PDF evidence from Chroma using local CPU embeddings.
- Routes tasks dynamically rather than running every agent for every question.
- Uses OpenAI and Google Gemini through explicit per-agent configuration.
- Shares Tavily Remote MCP search between Research and Code.
- Preserves document/page/chunk references and validates generated citation IDs
  and web URLs against supplied evidence.
- Streams agent output and graph updates through FastAPI Server-Sent Events.
- Runs the React frontend and API together in one Docker container.

The supervisor is prompted to check the distributed systems paper corpus before
web research, except for explicit web-only requests. This is a prompt policy,
not a deterministic guarantee. Each request is independent; visible chat history
is not sent back as conversation memory.

## Quick start: Docker

Prerequisites: Docker Desktop running Linux containers, API credentials for
OpenAI, Google Gemini, and Tavily, and research PDFs in `data/corpus/`.
Copy `.env.example` to `.env` if you do not already have one, then fill in the
credentials and confirm the configured model names are available to your accounts.
Never commit `.env`.

Run from the repository root in PowerShell:

```powershell
$env:APP_PORT = "18000"
docker compose build
docker compose run --rm --no-deps app python -m app.services.document_rag
docker compose up -d
docker compose logs -f app
```

Wait for `Application startup complete`, then open http://127.0.0.1:18000.
The container uses local embeddings; the first ingestion downloads the model.
Chat queries and evaluation can use paid APIs. The corpus and raw evaluation
artifacts are not included in a Git checkout.

Compose mounts PDFs read-only and stores its Chroma index and embedding model
cache in named volumes. The container index is separate from a host Python index.
Stop with `docker compose down`; volumes persist. The default host port is 8001
if `APP_PORT` is unset. See [Docker instructions](docs/docker.md) for storage,
re-ingestion, and troubleshooting.

## Local development

Requirements: Python 3.13 and Node.js 22.12+ within the Node 22 release line.
Commands below use PowerShell; `npm.cmd` avoids PowerShell script restrictions.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd --prefix frontend ci
```

Prepare `.env` and `data/corpus/` as described above. Build the local document
index before asking document questions:

```powershell
.\.venv\Scripts\python.exe -m app.services.document_rag
```

Start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

In a second terminal:

```powershell
npm.cmd --prefix frontend run dev
```

Open http://127.0.0.1:5173. Vite forwards `/chat` and `/health` to port 8001.
Use another backend port in `frontend/vite.config.js` if 8001 is unavailable.
Stop a running Docker container first if it occupies the same host port.

To serve the frontend from FastAPI instead of Vite, run
`npm.cmd --prefix frontend run build`, then start FastAPI and open its URL.
Rebuild after frontend changes. Restart FastAPI if it started before the first
frontend build. `/health` checks HTTP availability; it does not validate the index
or API credentials.

## Example questions

- "How does Raft elect a leader?"
- "Compare the read paths of GFS and Spanner using the document corpus."
- "Write a simple Python retry function and inspect its syntax."
- "Search the web only for current official Python asyncio documentation."

The necessary papers must exist in your corpus. Agent selection and answer
quality depend on the query, retrieved evidence, and configured models.

## Verification and evaluation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend run build
```

Five focused offline tests cover health, empty-query rejection, retrieval
metadata, citation validation, and supervisor delegation with fake model/worker
responses. They do not exercise all agents, SSE UI behavior, or live MCP access.

Local Docker verification on 2026-10-28 covered image build, non-root execution,
health, frontend assets, dependency consistency, and document retrieval. Ingestion
indexed 15 papers into 1,891 chunks. Live provider behavior was not retested during
containerization; the owner also confirmed a document-first query worked locally.

A historical RAGAS experiment compared top-10 retrieval with continuation expansion
on 12 questions. Answer relevance increased from 0.7171 to 0.8939, with a trade-off
in context precision. This measures the Research pipeline on a small development
set, not end-to-end application accuracy. See [evaluation](docs/evaluation.md).

## Project map

| Location | Responsibility |
| --- | --- |
| `app/agents/` | Supervisor, specialized workers, graph state, citation checks |
| `app/services/` | PDF ingestion, Chroma retrieval, Tavily MCP search |
| `app/main.py` | FastAPI endpoints, SSE events, compiled frontend serving |
| `app/llm.py` | Per-agent OpenAI/Gemini model construction |
| `frontend/src/` | React UI, SSE reader, styling |
| `scripts/` | Optional answer collection and RAGAS scoring |
| `tests/` | Five offline tests and the evaluation question dataset |

Read the [architecture](docs/architecture.md) for execution flow and design trade-offs.

## Current limits

- Local portfolio application; no verified public or AWS deployment, user
  authentication, or production traffic handling.
- Citation validation checks reference identity, not whether every claim is true.
- PDF text extraction and retrieval can miss relevant passages.
- Index updates require stopping requests; ingestion is not an atomic swap.
- No measured end-to-end cost/latency benchmark or comprehensive live-agent coverage.
- The shared dependency set includes evaluation packages, so the image is relatively
  large. AWS integration is a future option, not an implemented feature.
