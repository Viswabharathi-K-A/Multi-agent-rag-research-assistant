
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from operator import add


AgentName = Literal["research", "code", "summary"]
NextNode = Literal["research", "code", "summary", "finish"]
RetrievalMode = Literal["documents", "web", "both"]


class AgentTask(TypedDict):
    agent: AgentName
    instruction: str
    # Used by research tasks; optional for existing tasks and other agents.
    retrieval_mode: NotRequired[RetrievalMode]
    search_query: NotRequired[str]
    allowed_domains: NotRequired[list[str]]


class AgentResult(TypedDict):
    agent: AgentName
    instruction: str
    content: str
    success: bool
    error: str | None
    sources: NotRequired[list[dict[str, Any]]]


class TraceEvent(TypedDict):
    node: str
    action: str
    detail: str
    provider: str | None
    model: str | None
    reason: str | None
    tool: NotRequired[str | None]


class ResearchState(TypedDict):
    # Original request
    user_query: str
    # Once established, source restrictions persist across delegations.
    allowed_domains: NotRequired[list[str]]

    # Supervisor planning
    current_task: AgentTask | None
    next_agent: NextNode

    # Accumulated agent outputs
    results: Annotated[list[AgentResult], add]

    # Final response
    final_answer: str

    # Execution safety
    iteration: int
    max_iterations: int

    # Observability
    trace: Annotated[list[TraceEvent], add]
