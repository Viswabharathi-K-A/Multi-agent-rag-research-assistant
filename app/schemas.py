
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=12000,
    )


class Citation(BaseModel):
    source_id: str
    document: str
    chunk_id: str | None = None
    page: int | None = None
    excerpt: str | None = None


class RoutingDecision(BaseModel):
    agent: str
    provider: str
    model: str
    reason: str


class AgentTrace(BaseModel):
    event: str
    agent: str | None = None
    details: dict[str, Any] = Field(
        default_factory=dict
    )


class StreamEvent(BaseModel):
    type: Literal[
        "start",
        "trace",
        "routing",
        "token",
        "citation",
        "done",
        "error",
    ]
    data: dict[str, Any] = Field(
        default_factory=dict
    )


class HealthResponse(BaseModel):
    status: Literal["ok"]
    application: str
    environment: str
