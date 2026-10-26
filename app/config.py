
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "CSCI599 Multi-Agent Research Assistant"
    app_env: str = "development"
    log_level: str = "INFO"

    openai_api_key: str | None = None
    google_api_key: str | None = None

    supervisor_provider: Literal["openai", "google"] = "openai"
    supervisor_model: str = "gpt-5.1"

    research_provider: Literal["openai", "google"] = "google"
    research_model: str = "gemini-2.5-flash"

    code_provider: Literal["openai", "google"] = "openai"
    code_model: str = "gpt-5.1"

    summary_provider: Literal["openai", "google"] = "google"
    summary_model: str = "gemini-2.5-flash"

    tavily_api_key: str | None = None
    tavily_timeout_seconds: float = Field(default=30, gt=0, le=120)
    tavily_max_results: int = Field(default=5, ge=1, le=10)
    research_timeout_seconds: float = Field(default=60, gt=0, le=180)

    chroma_persist_dir: Path = Path("./data/chroma_index")
    chroma_collection: str = "technical_documents"
    corpus_dir: Path = Path("./data/corpus")

    embedding_model: str = (
        "sentence-transformers/all-MiniLM-L6-v2"
    )

    retrieval_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
    )

    gcp_project_id: str = ""
    gcp_region: str = "us-west1"
    cloud_run_service: str = "csci599-multi-agent"

    def resolve_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path

        return (PROJECT_ROOT / path).resolve()

    @property
    def chroma_path(self) -> Path:
        return self.resolve_path(self.chroma_persist_dir)

    @property
    def documents_path(self) -> Path:
        return self.resolve_path(self.corpus_dir)

    def validate_runtime(self) -> None:
        required = {
            "OPENAI_API_KEY": self.openai_api_key,
            "GOOGLE_API_KEY": self.google_api_key,
            "TAVILY_API_KEY": self.tavily_api_key,
        }
        for role in ("supervisor", "research", "code", "summary"):
            required[f"{role.upper()}_MODEL"] = getattr(self, f"{role}_model")

        missing = [
            name
            for name, value in required.items()
            if not value or not value.strip()
        ]

        if missing:
            raise ValueError(
                "Missing required configuration: "
                + ", ".join(missing)
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
