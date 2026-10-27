# Architecture and implementation status

Updated: 2026-10-26. Assignment basis: `Assignment_2_Description.pdf`, especially sections 2.1-2.5, 3.1, 3.3-3.5, and rubric 7.2. This document describes current source code and verification. `architecture_review.md` and `implementation_notes.md` describe earlier development stages.

## Current scope

Implemented: supervisor decisions, Research document/web source selection, corpus ingestion, Chroma retrieval, LCEL evidence augmentation and generation, Tavily Remote MCP, provider configuration, and offline tests. FastAPI currently serves a frontend shell and health endpoint.

The RAG plumbing is implemented and tested with fixtures. The selected local corpus contains 15 distributed systems research PDFs; extraction and chunking have been checked on those files. Production indexing with real embeddings, retrieval evaluation, Code and Summary workers, complete graph execution, chat/SSE integration, dynamic provider routing, exercised MCP sharing, and Cloud Run deployment remain incomplete.

## Components and orchestration

| File | Responsibility | Status |
| --- | --- | --- |
| `app/agents/supervisor.py` | Select a worker, instruction, research retrieval mode, and rationale using structured LLM output. | Implemented; source-selection mapping checked with mocks during development. |
| `app/agents/research.py` | Retrieve evidence, augment a prompt, generate findings, and return sources and traces. | Implemented; persistent offline tests. |
| `app/services/document_rag.py` | Load PDF pages, chunk their text, manually rebuild a local Chroma collection, and retrieve chunks. | Implemented; real Chroma tested with fake embeddings. |
| `app/services/tavily_mcp.py` | Discover and invoke Tavily search through Remote MCP; normalize web evidence. | Implemented; live compatibility unverified. |
| `app/llm.py` | Construct the configured OpenAI or Google chat model for each role. | Implemented; live model compatibility unverified. |
| `app/agents/state.py` | Define task, result, trace, and graph-state contracts and reducers. | Implemented. |
| `app/agents/agents.py` | Define supervisor-to-worker routing and worker-to-supervisor edges. | Incomplete: imports missing `code.py` and `summary.py`. |
| `app/main.py` | Serve static frontend assets and `/health`. | Implemented; no chat/SSE endpoint yet. |

The intended connected flow is below. Research paths execute in isolation and in a small test graph; this diagram does not imply the incomplete production graph runs end to end.

```mermaid
flowchart TD
    Q[User query] --> S[LLM supervisor]
    S -->|instruction and retrieval_mode| R[Research worker]
    R --> D[Chroma document retrieval]
    R --> W[Tavily Remote MCP search]
    D --> E[Evidence with source metadata]
    W --> E
    E --> P[Augmented prompt]
    P --> L[Configured research LLM]
    L --> O[Findings, sources and trace deltas]
    R -->|failure and collected evidence| O
    O --> S
    S -.-> C[Code worker: pending]
    S -.-> U[Summary worker: pending]
    S --> F[Final answer in graph state]
```

The intended orchestration pattern is a central supervisor. Code and Summary are planned specialists; the supervisor does not count toward the three-specialist requirement. Research currently has document retrieval and Tavily access; distinct tools/prompts for the other specialists remain to be implemented.

### Shared state

| Contract | Fields and behavior |
| --- | --- |
| `AgentTask` | Required `agent` and `instruction`; optional `retrieval_mode` (`documents`, `web`, `both`). |
| `AgentResult` | `agent`, `instruction`, `content`, `success`, `error`; optional structured `sources`. |
| `TraceEvent` | Node, action, detail, provider, model, rationale; optional tool name. |
| `ResearchState` | Original query, messages, tasks/current task, next agent, results, final answer, iteration limits, and trace. |

`results` and `trace` use additive reducers. Workers return only new entries, so LangGraph appends them without duplicating history. `messages` uses LangGraph's `add_messages` reducer. TypedDict contracts describe dictionary shapes; they do not enforce runtime validation. The supervisor's Pydantic decision validates its structured retrieval mode, and Research also checks the mode at runtime.

## Research source selection

The supervisor prompt asks the LLM to choose evidence sources and explain its choice in `reason`. The selected mode is included in `current_task` and in the supervisor trace detail. Research also traces each retrieval tool.

| Mode | Research behavior | Example intent |
| --- | --- | --- |
| `documents` | Chroma only; also the default when the task omits a mode. | Answer from the provided corpus. |
| `web` | Tavily MCP only. | Search for current external information. |
| `both` | Retrieve documents, then search Tavily. | Compare corpus material with current information. |

The supervisor prompt defaults ambiguous requests to documents and instructs it to respect explicit source restrictions. Research enforces the delegated mode; it does not independently interpret the original query's source restrictions. Actual LLM selection quality has not been verified live.

A failed channel returns worker failure without an automatic fallback. In `both` mode, a document failure stops before web retrieval; a later web failure preserves collected document evidence. An empty result list is different from an exception: if one channel returns an empty list and the other supplies evidence, generation can proceed. Missing or empty Chroma indexes raise errors rather than returning empty results. With no evidence at all, Research skips model creation and generation.

## Document ingestion and retrieval

The corpus is 15 local distributed systems research papers in `data/corpus`, including Raft, GFS, Spanner, Borg, MapReduce, and Practical Byzantine Fault Tolerance. Research papers are an accepted corpus under assignment section 2.4. A local extraction check produced 1,891 chunks from 249 text-bearing PDF pages. These counts demonstrate extraction, not retrieval quality or answer faithfulness; those require evaluation. The ignored `data/` directory is not included in Git, so corpus acquisition/source attribution and availability for reproduction must be documented before submission.

The strategy is deliberately static: manually place PDFs in the corpus directory and run ingestion when needed. There is no repository downloader, automatic synchronization, manifest, checksum, or commit tracking.

`app/services/document_rag.py` uses the existing configuration:

| Setting | Default |
| --- | --- |
| `CORPUS_DIR` | `./data/corpus` |
| `CHROMA_PERSIST_DIR` | `./data/chroma_index` |
| `CHROMA_COLLECTION` | `technical_documents` |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` |
| `RETRIEVAL_TOP_K` | `10` (provisional) |

Relative configured directories resolve against the project root.

1. `load_chunks()` recursively reads `.pdf` files, case-insensitively, using `pypdf`. Other extensions and symlinks are ignored. The filename stem supplies the title. Empty-password encryption is supported; files requiring a password, corrupt PDFs, and papers with no extractable text fail ingestion. Blank pages are skipped without renumbering later pages. There is no OCR fallback.
2. Each page is split independently with `RecursiveCharacterTextSplitter`: 800-character chunks, 120-character configured overlap, and start offsets within the page. Chunks never cross pages. These are initial settings, not evaluated optima or token limits. PDF column order, tables, and figures can limit extracted evidence.
3. Metadata preserves `source` (corpus-relative path), `title`, `page` (1-based PDF file page), `source_kind`, `document_id`, `chunk_id`, and `start_index`. For `raft.pdf`, a document ID is `document:raft.pdf` and a chunk ID is `raft.pdf:p7:c1`. IDs use path and position, not content hashes; changing the text can retain the same ID, so IDs are not historical versions. PDF file pages may differ from printed paper page numbers.
4. `get_embeddings()` lazily loads the configured Hugging Face model on CPU and caches one model instance. Vectors are normalized. The initial model use may download weights; local embedding uses no paid embedding API. PyTorch and Transformers increase dependency size and cold-start work.
5. `ingest_documents()` re-embeds every chunk on each manual run, preparing all vectors in batches of 64 before writing evidence. It then upserts chunks and removes obsolete IDs in batches of 64. The configured collection is dedicated to this corpus. Extraction or embedding failures preserve existing evidence; failed writes propagate and can leave a partial rebuild. No change detection is needed.
6. `get_vector_store()` checks the collection's embedding-model name against configuration. A changed model name requires a new collection name. Retrieval never creates a missing collection or automatically ingests documents.
7. `retrieve_documents()` uses a LangChain Chroma retriever for top-k vector similarity and returns `Document` objects with their metadata. There is no relevance cutoff or reranking; similarity alone does not prove a chunk answers the question.

An offline comparison on the 12 fixed questions increased coverage of all reference file/page pairs per question from 10/12 questions at k=5 to 11/12 at k=10. Total reference file/page pairs found increased from 10/13 to 12/13, while average retrieved text grew from approximately 3,778 to 7,548 characters. The missing Raft election passage ranked eighth. The cross-paper comparison still lacked required passages, and page matches did not guarantee that every required fact was present. The default is provisionally 10; answer-quality evaluation is still needed to justify the extra context and generation cost. Changing k does not require re-ingestion.

Run ingestion explicitly after preparing the corpus:

```powershell
.\.venv\Scripts\python.exe -m app.services.document_rag
```

The command prints counts for `documents`, `chunks`, `embedded_chunks`, and `removed_chunks`. Ingestion is a manual rebuild, not an atomic index swap. Run it while requests are stopped. Failed multi-batch writes can leave some new chunks alongside old chunks until a successful rerun. The production PDF index has not yet been built. Preparing a deployment index and packaging model assets remain deployment work; request handlers should not rebuild the corpus.

## LCEL augmentation and generation

The Research chain is:

```python
RunnableLambda(retrieve_evidence) | prompt | RunnableLambda(generate_findings) | StrOutputParser()
```

`chain.ainvoke()` supplies the original query, research instruction, and retrieval mode. `retrieve_evidence()` calls the selected services and returns a dictionary whose `research_context` value is JSON containing that request and the normalized sources. The human prompt template `{research_context}` is filled from that dictionary key. The system prompt instructs the model to treat source text as untrusted evidence, cite supplied sources, distinguish interpretation and uncertainty, and acknowledge missing support.

`generate_findings()` invokes the shared research-model factory only after evidence exists. `StrOutputParser` extracts text from the model response, including supported text-block responses. Blank output becomes failure. A source appendix is added after generation.

### Evidence and citation contract

All evidence entries contain `source_id`, `source_kind`, `title`, `content`, and `metadata`.

- Document entries use the original chunk ID as `source_id`, include the relative PDF path as `source`, and retain page, document/chunk IDs, and offsets in metadata. The prompt requests the supplied title and PDF page alongside inline `[source_id]` citations, for example `(raft, PDF page 7) [raft.pdf:p7:c1]`. It forbids inventing missing page numbers.
- Web entries retain the Tavily URL as `url` and receive `source_kind="web"`. The prompt requests exact inline URLs. Web IDs such as `web-1` are local to each search, not globally unique across tasks.
- The structured `AgentResult.sources` preserves snippets. Python builds the text appendix from retrieved metadata, listing IDs, titles, paths, and available PDF pages, or web URLs. Missing page metadata adds no page reference. It does not duplicate snippets within the textual report; the supervisor currently serializes full results, including structured evidence, into its context.

Source preservation does not validate claim entailment or ensure every generated reference is correct. Document paths are identifiers, not yet clickable document-serving endpoints. Final citation preservation through the pending Summary worker, supervisor output, and frontend still needs verification.

### Async behavior and failures

Research is async and must run through graph `ainvoke`/`astream`. Synchronous Chroma retrieval runs via `asyncio.to_thread()` so it does not directly block the event loop. Cancellation or timeout stops awaiting that thread but cannot forcibly stop its underlying computation.

The combined retrieval stage has `RESEARCH_TIMEOUT_SECONDS` (default 60 seconds); synthesis has a separate timeout of the same duration. Tavily also has its own `TAVILY_TIMEOUT_SECONDS` (default 30 seconds). These are stage limits, not a whole-workflow deadline. The provider factory currently retains `max_retries=2` and a 30-second provider timeout.

Invalid tasks, invalid modes, retrieval failures, missing evidence, blank generation, and model errors return `success=False` with safe error text. Collected sources survive subsequent failures. Cancellation propagates to the caller. Tests cover these worker behaviors; full supervisor recovery and production graph failure isolation remain unverified.

## Tavily Remote MCP

`search_web()` opens a request-scoped Streamable HTTP transport, initializes `ClientSession`, lists tools, invokes search, normalizes results, and closes the session/transport. Authentication uses the assignment endpoint pattern `https://mcp.tavily.com/mcp/?tavilyApiKey=<encoded-key>`; credentials remain in the environment or ignored `.env`.

The current implementation lists one page of tools, selects the first `tavily_search` or `tavily-search` with a string `query` property, adds supported `search_depth`/`max_results` arguments, and checks required argument names. It does not implement discovery pagination, arbitrary capability selection, or full JSON-schema validation.

Structured content or JSON-text results are normalized to usable HTTP(S) URLs with snippets. Exact URLs are deduplicated; result count is capped by configuration, titles at 500 characters, and snippets at 6,000 characters. Optional score, publication date, and author metadata are retained. Malformed results fail safely.

Filters on `httpx2` and `mcp.client.streamable_http` suppress records containing the Tavily endpoint or query-key marker, including exception text. This is not universal credential redaction for arbitrary logs or tracing. There are no application-level search retries or pooled sessions. Only Research currently invokes Tavily; sharing the service function does not satisfy the rubric's requirement that multiple agents actually invoke the same MCP tool.

## LLM routing and application boundary

| Role | Configured provider/model defaults | Current status |
| --- | --- | --- |
| Supervisor | OpenAI / `gpt-5.1` | Decision node implemented. |
| Research | Google / `gemini-3.5-flash-lite` | Worker implemented. |
| Code | OpenAI / `gpt-5.1` | Configuration only; worker missing. |
| Summary | Google / `gemini-3.5-flash-lite` | Configuration only; worker missing. |

These are static role assignments, not completed cost/capability routing. Research traces explicitly mark dynamic model routing as pending. Source selection and generation-provider routing are separate decisions. Model IDs are configured values; this work did not verify availability through live API calls.

The intended cost/capability policy uses Gemini 3.5 Flash-Lite for routine evidence extraction and short summaries, and GPT-5.1 for demanding code tasks and complex synthesis across sources. Flash-Lite is selected as a cost-efficient option; its parameter count and task quality are not assumed. Task-dependent routing and measured quality/latency comparisons remain pending. The earlier live pilot received a model-unavailable 404 for `gemini-2.5-flash`; the Flash-Lite replacement is configured but has not yet been tested live. Its project-specific quota must be respected during testing and deployment.

`Settings` reads the root `.env` and environment overrides. `validate_runtime()` exists but is not called by startup. FastAPI does not yet invoke the graph, stream tokens, or expose document citations. The design intends single-turn requests; durable conversation memory is not currently claimed. A Chroma index is separate from conversation persistence, and its Cloud Run packaging remains unverified.

## Verification

Current persistent offline suite: **46 passed** on 2026-10-26:

| File | Cases | What is exercised |
| --- | --- | --- |
| `tests/test_health.py` | 4 | Health endpoint, homepage, static CSS, and missing route. |
| `tests/test_document_rag.py` | 17 | Mocked PDF extraction and real temporary Chroma with deterministic fake embeddings: page metadata, blank pages, repeat ingestion, edits/deletions, encryption, corrupt/empty input, embedding failures, model mismatch, and batching. |
| `tests/test_research.py` | 25 | Real LCEL with mocked retrieval/model calls: modes, augmentation, PDF page/chunk references, missing pages, combined web citations, validation, empty evidence, failures, text formats, timeout, cancellation, and a small real LangGraph's additive reducers. |

Additional one-off development checks exercised supervisor mode mapping with mocked structured decisions and a real temporary Chroma-to-Research-to-LangGraph path with fake embeddings and generation. Those checks are not persistent tests. The current suite does not contain the older `test_research_mcp.py` referenced in prior notes; historical 42-test/MCP coverage claims are not evidence for this checkout.

Run offline checks from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/test_document_rag.py tests/test_research.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pip check
```

Pytest excludes the `live` marker by default. No live test is currently shipped. Paid/quota-limited tests require separate explicit approval; implementing a feature does not authorize API spending. This development used no paid APIs or model-weight downloads. Real embeddings/retrieval quality, Tavily authentication and remote schema compatibility, generation-model behavior, supervisor source-choice quality, full production execution, and Cloud Run behavior remain unverified.

## Remaining work

- **P0 - Corpus and evaluation:** Document sources and reproduction instructions for the selected papers, build their index with real embeddings, and evaluate chunking/retrieval. Define fixed paper-specific questions and reference answers grounded in actual passages, retain retrieved chunks and generated answers, and report RAGAS faithfulness, answer relevance, context precision, and context recall with concrete results in `docs/evaluation.md`. Mocked unit tests do not substitute for this evaluation; paid evaluator/generation calls require approval.
- **P0 - Specialists and orchestration:** Implement distinct Code and Summary workers with appropriate tools/prompts; exercise the full async graph and preserve citations through the final answer.
- **P0 - Provider routing and MCP sharing:** Implement inspectable cost/capability routing across providers, and have a second agent invoke the same MCP tool in a useful distinct context.
- **P0 - Delivery:** Connect chat/SSE and citation/trace UI, prepare a Linux-compatible container and Chroma/model assets, deploy to Cloud Run, and complete README, evaluation, and process-log deliverables.
- **P1 - Persistent integration coverage:** Add supervisor source-selection and full-graph recovery tests as those components become operational. Restore focused MCP transport/schema/response tests for the current service and separately budget any live compatibility check.
- **P1 - Grounding and reliability:** Validate source references, bound workflow/context costs, measure cold/warm latency, and review provider retries. Citation-reference checks alone cannot establish factual entailment.

## Shared dependency environment

As of 2026-10-27, application execution, offline tests, answer collection, and RAGAS scoring use the same Python 3.13 `.venv`, installed from `requirements.txt`. There is no separate evaluation requirements file. The combined set was validated in a clean temporary environment with 96 passing offline tests, RAGAS imports, graph compilation, and offline provider/tool construction. OpenAI SDK 2.54.0 and jiter 0.14.0 resolve the Instructor/RAGAS conflict; pydantic-settings 2.16.1 and python-dotenv 1.2.4 satisfy the combined dependencies. LangChain Community 0.3.31 retains a module RAGAS imports. Model IDs are independent of SDK versions. Linux/Cloud Run installation and live compatibility of the consolidated SDK set remain unverified; existing RAGAS measurements are preserved in [evaluation.md](evaluation.md).

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```
