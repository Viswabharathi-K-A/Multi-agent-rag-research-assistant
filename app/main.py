
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessageChunk
from sse_starlette.sse import EventSourceResponse

from app.agents.agents import build_agent_graph
from app.config import get_settings
from app.schemas import (
    AgentTrace, ChatRequest, Citation, HealthResponse, RoutingDecision, StreamEvent,
)
from app.services.document_rag import get_embeddings


settings = get_settings()

logging.basicConfig(
    level=getattr(
        logging,
        settings.log_level.upper(),
        logging.INFO,
    ),
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    ),
)

logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting application: %s",
        settings.app_name,
    )

    if settings.app_env == "development":
        settings.documents_path.mkdir(
            parents=True,
            exist_ok=True,
        )

    logger.info("Initializing document embedding model")
    started = perf_counter()
    await asyncio.to_thread(get_embeddings, settings.embedding_model)
    logger.info("Document embedding model ready in %.2f seconds", perf_counter() - started)

    yield

    logger.info(
        "Shutting down application: %s",
        settings.app_name,
    )


app = FastAPI(
    title=settings.app_name,
    description=(
        "Multi-agent technical research assistant "
        "using LangGraph, RAG, MCP and LLM routing."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Allow API-only development before the frontend has been built.
if (FRONTEND_DIR / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIR / "assets")),
        name="assets",
    )


@app.get("/", include_in_schema=False)
async def homepage():
    index = FRONTEND_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(
            status_code=503,
            detail="Frontend not built. Run 'npm.cmd --prefix frontend run build' "
                   "from the project root, then restart FastAPI.",
        )
    return FileResponse(index)


@app.get(
    "/health",
    response_model=HealthResponse,
)
async def health():
    return HealthResponse(
        status="ok",
        application=settings.app_name,
        environment=settings.app_env,
    )


@app.post("/chat")
async def chat(request: ChatRequest):
    """Run one graph request and stream generation fragments and graph updates."""

    def event(kind: str, data: dict) -> dict:
        return {"event": kind, "data": StreamEvent(type=kind, data=data).model_dump_json()}

    async def events():
        yield event("start", {"query": request.query})
        seen_sources = set()
        final_answer = None
        try:
            graph = build_agent_graph()
            async for mode, payload in graph.astream(
                {"user_query": request.query, "iteration": 0, "max_iterations": 8},
                config={"recursion_limit": 20},
                stream_mode=["messages", "updates"],
            ):
                if mode == "messages":
                    chunk, metadata = payload
                    agent = metadata.get("langgraph_node")
                    # Supervisor output contains structured control fields, not answer tokens.
                    if agent not in ("research", "code", "summary") or not isinstance(chunk, AIMessageChunk):
                        continue
                    if isinstance(chunk.content, str):
                        text = chunk.content
                    else:
                        text = "".join(
                            block["text"] for block in chunk.content
                            if isinstance(block, dict) and block.get("type") == "text"
                        )
                    if text:
                        yield event("token", {"agent": agent, "text": text})
                    continue

                for node, update in payload.items():
                    for trace in update.get("trace", []):
                        yield event("trace", AgentTrace(
                            event=trace["action"], agent=trace["node"],
                            details={key: value for key, value in trace.items()
                                     if key not in ("action", "node")},
                        ).model_dump())
                        if (trace["action"] in ("llm_started", "delegate", "finish")
                                and trace.get("provider") and trace.get("model")):
                            yield event("routing", RoutingDecision(
                                agent=trace["node"], provider=trace["provider"],
                                model=trace["model"], reason=trace["reason"],
                            ).model_dump())
                    for result in update.get("results", []):
                        for source in result.get("sources", []):
                            document = source["url"] if source["source_kind"] == "web" else source["source"]
                            key = (document, source["source_id"])
                            if key in seen_sources:
                                continue
                            seen_sources.add(key)
                            metadata = source.get("metadata", {})
                            yield event("citation", Citation(
                                source_id=source["source_id"], document=document,
                                chunk_id=metadata.get("chunk_id"), page=metadata.get("page"),
                                excerpt=source["content"],
                            ).model_dump())
                    if node == "supervisor" and update.get("next_agent") == "finish":
                        final_answer = update.get("final_answer", "")
            if not final_answer:
                yield event("error", {"message": "The workflow did not produce a final answer."})
            else:
                yield event("done", {"final_answer": final_answer})
        except Exception:
            # Provider exceptions can contain credentials or request content.
            logger.error("Chat workflow failed")
            yield event("error", {"message": "The request could not be completed. Please try again."})

    return EventSourceResponse(events(), headers={"Cache-Control": "no-cache"})
