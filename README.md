# Multi-agent research assistant

USC CSCI 599 Assignment 2: LangGraph orchestrates Research, Code, and Summary
specialists behind FastAPI and a vanilla HTML/CSS/JavaScript SSE frontend.
Research uses a Chroma-backed LCEL RAG pipeline and Tavily Remote MCP. Research
and Code share the MCP search integration. Provider/model choices and reasons,
execution traces, and source excerpts are inspectable in the UI.

Public application: [Cloud Run](https://csci599-multi-agent-b7rvvpibna-uw.a.run.app/).
Revision `csci599-multi-agent-00002-xpp` serves the updated corpus-aware supervisor
prompt. Public homepage/health checks and live document/web requests succeeded.

## Local setup

Use Python 3.13. The pinned environment has been verified on Windows, and the
Linux/amd64 Docker image passed local build, startup, and document-retrieval checks.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` locally with OpenAI, Google, and Tavily keys. Never commit it. Defaults
assign OpenAI to Supervisor/Code and Google to Research/Summary; model IDs and
provider assignments are configurable. Check account access to the configured
models before live use. No paid API calls are made by normal offline tests.

Supply the approved PDFs under `data/corpus/`; this directory is intentionally
not tracked. The recorded corpus contains 15 distributed-systems papers, 249
text-bearing pages, and 1,891 chunks. Publication/acquisition links and edition
caveats are documented in [corpus attribution](docs/architecture.md#corpus-attribution-and-acquisition).
The exact PDF editions must accompany reproduction separately; a Git checkout is insufficient.

```powershell
# Explicit offline ingestion; may download public embedding model assets.
.\.venv\Scripts\python.exe -m app.services.document_rag
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. Startup loads cached CPU embeddings before serving.
Keep ingestion separate from requests; do not rebuild the index while serving.
Changing embedding models requires a new collection and re-ingestion.

Example: “Use Research, Code, and Summary agents to explain Raft leader election,
provide pseudocode, and summarize the findings. Use only the provided documents.”
This query makes paid generation calls. Web research additionally uses Tavily quota.

## Tests and evaluation

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not live" -q -p no:cacheprovider
node -e "const html=require('fs').readFileSync('app/static/index.html','utf8'); new (require('vm').Script)(html.match(/<script>([\s\S]*?)<\/script>/)[1]);"
```

The latest recorded full offline suite passed **292 tests in 14.63 seconds**;
verification details are recorded in [architecture.md](docs/architecture.md). Tests use mocked
model/MCP boundaries and fake embeddings, including real graph execution and
temporary Chroma integration. Passing them does not establish live model quality.

The frontend is self-contained in `app/static/index.html`, with embedded CSS and
vanilla JavaScript. The Node command above checks its inline script without
executing it or calling any APIs.

[Evaluation results](docs/evaluation.md) report two 12-question Research-only
RAGAS runs. Continuation retrieval improved answer relevance from 0.7171 to 0.8939
and context recall from 0.9514 to 1.0000, with lower context precision and more
input context. These results do not measure the complete multi-agent workflow.

The collection and scoring commands below are **paid operations**; run only after
approving a budget. Use fresh output names; existing artifacts are not overwritten.

```powershell
.\.venv\Scripts\python.exe -m scripts.collect_rag_answers --run-live --output data/evaluation/new_answers.jsonl
.\.venv\Scripts\python.exe -m scripts.evaluate_rag --input data/evaluation/new_answers.jsonl --output data/evaluation/new_scores.json --judge-model gpt-4.1-mini --embedding-model text-embedding-3-small --run-live
```

## Container preparation

The Dockerfile uses three stages: `base` supplies Python and OS dependencies,
`build` installs the Python environment and indexes `data/corpus/`, and `runtime`
receives the installed environment, application, Chroma index, and model cache.
CPU-only PyTorch is installed from the official PyTorch index before the remaining
requirements, avoiding unused CUDA dependencies while retaining the pinned version.
The build downloads embedding assets and generates the index on Linux; runtime
model downloads are disabled and the server runs as a non-root user. No provider
keys are needed during image build. Original PDFs, local Windows indexes, evaluation
outputs, and submission documentation are excluded from the final runtime image.
Production document queries use the bundled index; startup warms cached embeddings.

An earlier multi-stage image built at **750,490,613 bytes (about 716 MiB)**.
Without API keys, its local smoke checks verified injected `PORT=8090`, HTTP 200 for
the homepage, `/health`, and `/static/app.js`, cached offline model loading,
document retrieval with citation metadata, all 1,891 indexed chunks, UID 10001,
and dependency consistency. The temporary container was stopped after testing.
Embedding warm-up took 29.80 seconds in that local run; this is not a Cloud Run
cold-start or TTFT measurement. The later deployed rebuild indexed the same 15
documents/1,891 chunks, contained the updated prompt, and passed `pip check`.
Confirmed deployed cold/warm timings are recorded in the evaluation report.

With Docker Desktop's Linux engine running:

```powershell
docker build --platform linux/amd64 -t csci599-multi-agent:local .
docker run --rm -p 8080:8080 --env-file .env csci599-multi-agent:local
```

The container listens on `0.0.0.0` using `PORT` (default 8080). Check
`http://localhost:8080/health` and the homepage first; these checks do not spend
provider credits. Chat does. The bundled index is an immutable deployment input:
Chroma can maintain local files, but runtime mutations are not durable cloud storage.
The application claims no persistent multi-turn conversation state.

## Cloud Run deployment recipe

The application is deployed; these commands describe setup for a fresh project,
using example repository/identity/secret names rather than the existing project's
exact resource names. The recipe has not been replayed in a second fresh project. Cloud
services, registry storage, build resources, and provider calls may incur charges.
Select a project and budget and complete the local image check first. Follow the
official [deployment guide](https://docs.cloud.google.com/run/docs/deploying) and
[secret configuration guide](https://docs.cloud.google.com/run/docs/configuring/services/secrets).

Install/authenticate the Google Cloud CLI and Docker. For a fresh project, enable
the APIs and create an image repository and runtime identity:

```powershell
$projectId = "YOUR_PROJECT_ID"
$region = "us-west1"
$service = "csci599-multi-agent"
$runtimeAccount = "csci599-runtime@${projectId}.iam.gserviceaccount.com"
$image = "${region}-docker.pkg.dev/${projectId}/app-images/${service}:release"
gcloud config set project $projectId
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
gcloud artifacts repositories create app-images --repository-format=docker --location=$region
gcloud iam service-accounts create csci599-runtime
gcloud auth configure-docker "${region}-docker.pkg.dev"
docker tag csci599-multi-agent:local $image
docker push $image
```

Create Secret Manager secrets named `openai-api-key`, `google-api-key`, and
`tavily-api-key` using the Cloud Console, each containing the corresponding key
alone. Do not upload `.env` as a secret value. Grant the runtime identity access:

```powershell
foreach ($secretName in @("openai-api-key", "google-api-key", "tavily-api-key")) {
    gcloud secrets add-iam-policy-binding $secretName --member="serviceAccount:$runtimeAccount" --role=roles/secretmanager.secretAccessor
}
```

Deploy a private service first, with pinned secret versions. The resource values
below are starting values to verify, not measured optimal settings. Substitute
the actual secret version numbers if they are not `1`.

```powershell
gcloud run deploy $service --image=$image --region=$region --service-account=$runtimeAccount --port=8080 --memory=4Gi --cpu=2 --timeout=300 --concurrency=1 --min-instances=0 --max-instances=1 --no-allow-unauthenticated --set-env-vars="APP_ENV=production" --set-secrets="OPENAI_API_KEY=openai-api-key:1,GOOGLE_API_KEY=google-api-key:1,TAVILY_API_KEY=tavily-api-key:1"
gcloud run services describe $service --region=$region --format="value(status.url)"
gcloud run services proxy $service --region=$region --port=8081
```

Use the authenticated proxy at `http://localhost:8081` for initial checks. When
ready to expose the service for grading, grant public invocation access:

```powershell
gcloud run services add-iam-policy-binding $service --project=$projectId --region=$region --member=allUsers --role=roles/run.invoker
```

The existing deployment already has this binding and was checked without
authentication. A public chat endpoint can consume API quota; the instance cap
is not a per-user usage limit or spending cap. Record your own resulting URL
and verify it works for the intended user.

## Costs, status, and limitations

With `LOG_LEVEL=INFO`, each completed or interrupted `/chat` stream emits a
`request_metrics` JSON log entry. Match its `request_id` to the response's
`X-Request-ID` header. It records server elapsed time, time to the first worker
token, model invocation timings, document/web retrieval timings, and provider-reported
input/output token counts. A direct Supervisor response has no worker-token timing.
Unknown usage remains null and is counted separately; known token totals are
partial when any calls lack usage. Unfinished model calls are also counted.
`generation_seconds` sums completed invocation durations, rather than wall-clock
request time. SDK retries are internal to an invocation and are not counted as
separate HTTP requests. Metrics omit prompts, answers, credentials, and error messages.

The approved live answer collector also writes a `measurements` object per JSONL
row. These measurements do not establish browser latency, cold/warm instance state,
or dollar cost. Capture client timings separately, correlate deployment logs by
request ID, and apply dated provider rates to reported usage. Do not run the
collector's `--run-live` option without approving API costs.

As of this project snapshot, corpus embeddings run locally; generation uses
OpenAI/Google and web search uses Tavily. RAGAS scoring separately uses an OpenAI
judge and evaluation embeddings. Provider access, quotas, and prices must be
checked in the relevant account before spending; this repository makes no fixed
price or free-tier claim. Capture actual input/output usage and searches, then
estimate cost using dated rates or actual bills. The evaluation report includes
dated standard-price generation estimates of $0.02575 for one C++ web request
and $0.02674 for one document request. These exclude Tavily, cloud charges,
credits, and discounts and are not actual bills.

One confirmed Cloud Run cold/warm pair used the same short Raft question.
Client first worker text arrived at **75.84 s cold / 4.76 s warm**; complete stream
times were **81.65 s / 10.71 s**. Startup logs confirmed a new instance for the
first request and the same instance for the repeat. This is one observation,
not a steady-state average. Both requests completed without stream errors.

Both generation providers were exercised in deployment. A separate local
same-evidence comparison found OpenAI/Gemini invocation times of 2.52/1.12 seconds
and generation estimates of $0.00647/$0.00168; both covered five required facts
and passed citation-ID checks. One question does not establish general provider
quality or deployed comparative performance. See the evaluation report for
prompts, usage, pricing sources, and limitations.

Selected local live checks demonstrated actual Research/Code Remote MCP sharing;
deployed request `05cedebe7fd446029cc78c538d57e4f0` also exercised the same Tavily tool from Research and Code, followed by Summary. The final response omitted the requested code snippet; shared-tool execution does not imply full task completion. Deployed
web Research recovered from an empty search, and Raft tests selected documents.
Broader completion-guard behavior, domain-schema enforcement, and provider-failure
handling remain incompletely verified live. Citation checks validate reference
identity, not every claim's support. Code inspection checks Python syntax without
execution. Each chat request starts fresh; no durable conversation history is claimed.

See [architecture](docs/architecture.md), [evaluation](docs/evaluation.md),
and [process log](PROCESS_LOG.md) for evidence and
remaining work. Corpus attribution is documented; final submission still needs
the exact corpus editions and raw artifacts/screenshots supplied separately as
appropriate and owner review of the
process log. The TA's updated length instruction is approximately 200 words per
section for `PROCESS_LOG.md` only, across its four required sections.
