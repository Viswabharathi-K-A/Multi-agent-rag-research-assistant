# Run with Docker

The image builds React in a Node stage, then copies the compiled files into a
Python 3.13 image. FastAPI serves the frontend and API together. Node is not
needed in the running container. Uvicorn runs as a non-root user, with one worker.

## Prerequisites

- Start Docker Desktop using Linux containers.
- Keep API credentials and model settings in the repository-root `.env`.
- Put your research PDFs in `data/corpus/`.
- Stop any local server using port 8001, or choose another host port as shown below.

The build downloads Node/Python dependencies. CPU-only PyTorch avoids GPU
dependencies, but the image can still be large. The first ingestion downloads
the configured Hugging Face embedding model; later runs reuse its cache.
These downloads do not call paid LLM APIs. Sending chat questions can incur
OpenAI, Gemini, and Tavily charges.

## Build and ingest

Run from the repository root:

```powershell
docker compose build
docker compose run --rm --no-deps app python -m app.services.document_rag
```

Ingestion reads the PDFs and creates a separate container-managed Chroma index.
It uses local CPU embeddings, not a paid embedding API. Your existing host index
in `data/chroma_index` is not modified or reused. The corpus is mounted read-only.

## Start

```powershell
docker compose up -d
docker compose logs -f app
```

Wait for `Application startup complete`, then open http://127.0.0.1:8001.
Press Ctrl+C to stop following logs; the container keeps running.

```powershell
docker compose ps
Invoke-RestMethod http://127.0.0.1:8001/health
```

If port 8001 is occupied or reserved by Windows, select another host port:

```powershell
$env:APP_PORT = "18000"
docker compose up -d
```

Then open http://127.0.0.1:18000. Keep the same `APP_PORT` value for subsequent
Compose commands; the container still listens on port 8000 internally.

Health checks start after a startup grace period. Model loading may take time.
A healthy status confirms HTTP availability, not index readiness or provider
credentials. Verify ingestion succeeded before testing document questions.

## Update documents or code

Stop the application before ingestion, because index writes are not atomic:

```powershell
docker compose stop app
docker compose run --rm --no-deps app python -m app.services.document_rag
docker compose up -d
```

After source or dependency changes, rebuild and recreate the container:

```powershell
docker compose up -d --build
```

React is built inside Docker; no host Node installation or separate Vite server
is needed. The Vite development proxy is not used in the built frontend.

## Storage and credentials

- `data/corpus/`: host PDFs mounted read-only.
- `chroma-data`: named volume holding the container's Chroma index.
- `model-cache`: named volume holding downloaded embedding model files.
- `.env`: supplied at runtime; excluded from the image.

Compose overrides corpus/index paths with Linux paths, so Windows paths from
`.env` do not carry into the container. If you change the embedding model, use
a new Chroma collection name and ingest again before starting the app.

Do not publish `.env` or paste expanded `docker compose config` output: it can
contain credentials. To validate configuration without printing values, use
`docker compose config --quiet`.

## Stop

```powershell
docker compose down
```

This removes the container and network while keeping both named volumes.
Avoid `docker compose down -v` unless you intend to delete the container index
and downloaded model cache. Host PDFs are not stored in these volumes.

## Troubleshooting

- Docker engine connection errors: start Docker Desktop and wait until ready.
- Port already allocated: stop the process using 8001 or change the host port.
- First startup fails to download a model: check container internet access and
  retry; startup requires the configured embedding model.
- Missing document index: run the ingestion command above.
- Build dependency errors after changing requirements: inspect the resolver's
  error before changing versions, then rebuild and repeat startup verification.

## Verified locally (2026-10-28)

- Linux image build, including the React production build, succeeded.
- `pip check` inside the container reported no broken requirements.
- Ingestion indexed 15 papers and 1,891 chunks using CPU embeddings.
- Local retrieval returned evidence with source, page, and chunk identifiers.
- Homepage, JavaScript, CSS, and health endpoint returned successful responses.
- The container ran as UID 1000 and reached healthy status.
- All five offline tests passed on the host.
- No paid chat or external research calls were made; live provider behavior was
  not verified by these checks.

Port 8001 was rejected by Windows during verification, so the running container
uses `APP_PORT=18000`. Open http://127.0.0.1:18000 for this run.
