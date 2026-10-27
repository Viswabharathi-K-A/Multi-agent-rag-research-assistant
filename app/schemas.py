
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """One single-turn chat request; queries must contain non-whitespace text."""

    query: str = Field(
        min_length=1,
        max_length=12000,
    )

    @field_validator("query")
    @classmethod
    def strip_query(cls, query: str) -> str:
        query = query.strip()
        if not query:
            raise ValueError("Query must contain non-whitespace text")
        return query


class Citation(BaseModel):
    """A source reference; document is a corpus-relative path or a web URL."""

    source_id: str
    document: str
    chunk_id: str | None = None
    page: int | None = None
    excerpt: str | None = None


class RoutingDecision(BaseModel):
    """The agent call's configured provider/model and selection rationale."""

    agent: str
    provider: str
    model: str
    reason: str


class AgentTrace(BaseModel):
    """A graph action, its agent, and the remaining trace fields in details."""

    event: str
    agent: str | None = None
    details: dict[str, Any] = Field(
        default_factory=dict
    )


class StreamEvent(BaseModel):
    """JSON envelope carried by an SSE message.

    Payload contracts (data remains a dictionary, not a validated union):
    - start: query
    - trace: AgentTrace fields
    - routing: RoutingDecision fields
    - token: agent, text (a generation fragment, not necessarily one tokenizer token)
    - citation: Citation fields
    - done: final_answer (the authoritative completed response)
    - error: message (safe user-facing text)

    Token text must come from ongoing generation. Intermediate worker text is
    labeled by agent; done supplies the final answer. Structured supervisor
    control output and tool arguments must not be displayed as answer text.
    """

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
