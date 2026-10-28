FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf-cache \
    PORT=8080

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

FROM base AS build
COPY requirements.txt ./
# Match the requirements pin while avoiding unused CUDA libraries on Linux.
RUN python -m pip install --no-cache-dir torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
# Build from the supplied corpus on Linux rather than copying a Windows index.
COPY data/corpus/ ./data/corpus/
RUN python -m app.services.document_rag \
    && chown -R appuser:appuser /app/data /opt/hf-cache

FROM base AS runtime
COPY --from=build /usr/local/ /usr/local/
COPY --from=build /app/app/ /app/app/
COPY --from=build --chown=appuser:appuser /app/data/chroma_index/ /app/data/chroma_index/
COPY --from=build --chown=appuser:appuser /opt/hf-cache/ /opt/hf-cache/

# Model assets and index are baked in; serving must not download or re-ingest.
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
USER appuser
EXPOSE 8080
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
