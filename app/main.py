
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.schemas import HealthResponse


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

STATIC_DIR = Path(__file__).parent / "static"


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

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)


@app.get("/", include_in_schema=False)
async def homepage():
    return FileResponse(
        STATIC_DIR / "index.html"
    )


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
