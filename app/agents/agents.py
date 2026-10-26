
from langgraph.graph import StateGraph, START, END

from app.agents.state import ResearchState
from app.agents.supervisor import supervisor_node
from app.agents.research import research_node
from app.agents.code import code_node
from app.agents.summary import summary_node


def route_from_supervisor(state: ResearchState) -> str:
    """Return the next node selected by the supervisor."""
    return state["next_agent"]


def build_agent_graph():
    """Construct and compile the multi-agent workflow."""

    graph = StateGraph(ResearchState)

    # Register nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("research", research_node)
    graph.add_node("code", code_node)
    graph.add_node("summary", summary_node)

    # Every request starts with the supervisor
    graph.add_edge(START, "supervisor")

    # Supervisor dynamically selects the next step
    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "research": "research",
            "code": "code",
            "summary": "summary",
            "finish": END,
        },
    )

    # Workers return control to the supervisor
    graph.add_edge("research", "supervisor")
    graph.add_edge("code", "supervisor")
    graph.add_edge("summary", "supervisor")

    return graph.compile()
