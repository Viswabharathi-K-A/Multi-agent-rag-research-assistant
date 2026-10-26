
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage
from operator import add


AgentName = Literal["research", "code", "summary"]
NextNode = Literal["research", "code", "summary", "finish"]


class AgentTask(TypedDict):
    agent: AgentName
    instruction: str


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

    # Conversation history
    messages: Annotated[list[AnyMessage], add_messages]

    # Supervisor planning
    tasks: list[AgentTask]
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
