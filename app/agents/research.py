
import json

from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)
from tavily import TavilyClient

from app.agents.state import ResearchState
from app.config import get_settings
from app.llm import (
    get_agent_llm,
    get_agent_provider_info,
)


RESEARCH_PROMPT = """
You are a research specialist in a multi-agent system.

Your job is to analyze the provided evidence and
produce a useful research report.

Rules:
1. Base factual claims on the supplied evidence.
2. Cite source URLs for findings derived from web results.
3. Distinguish evidence from your own interpretation.
4. Identify uncertainty or missing information.
5. Do not invent sources or research findings.
6. If the evidence is insufficient, explain what is missing.
7. Return findings that another agent can use.
"""


def search_web(query: str) -> list[dict]:
    """Retrieve external evidence using Tavily."""

    settings = get_settings()

    if not settings.tavily_api_key:
        raise ValueError(
            "TAVILY_API_KEY is not configured"
        )

    client = TavilyClient(
        api_key=settings.tavily_api_key
    )

    response = client.search(
        query=query,
        search_depth="basic",
        max_results=5,
    )

    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
        }
        for item in response.get("results", [])
    ]


def research_node(state: ResearchState) -> dict:
    """Execute the supervisor's assigned research task."""

    task = state.get("current_task")

    if task is None or task["agent"] != "research":
        raise ValueError(
            "Research agent received an invalid task"
        )

    instruction = task["instruction"]

    provider, model = get_agent_provider_info("research")

    try:
        # Step 1: Retrieve external evidence
        sources = search_web(instruction)

        if not sources:
            raise ValueError(
                "No research sources were retrieved"
            )

        # Step 2: Obtain the assigned LLM
        llm = get_agent_llm("research")

        # Step 3: Generate grounded findings
        response = llm.invoke([
            SystemMessage(content=RESEARCH_PROMPT),
            HumanMessage(
                content=json.dumps(
                    {
                        "original_query": state["user_query"],
                        "research_instruction": instruction,
                        "sources": sources,
                    },
                    ensure_ascii=False,
                )
            ),
        ])

        content = (
            response.content
            if isinstance(response.content, str)
            else json.dumps(response.content)
        )

        return {
            "results": [{
                "agent": "research",
                "instruction": instruction,
                "content": content,
                "success": True,
                "error": None,
            }],
            "trace": [{
                "node": "research",
                "action": "research_completed",
                "detail": (
                    f"Retrieved {len(sources)} web sources "
                    "and synthesized findings"
                ),
                "provider": provider,
                "model": model,
                "reason": (
                    "Configured research model used "
                    "for evidence-grounded synthesis"
                ),
            }],
        }

    except Exception as exc:
        return {
            "results": [{
                "agent": "research",
                "instruction": instruction,
                "content": "",
                "success": False,
                "error": str(exc),
            }],
            "trace": [{
                "node": "research",
                "action": "research_failed",
                "detail": str(exc),
                "provider": provider,
                "model": model,
                "reason": (
                    "Research execution failed; "
                    "provider invocation may not "
                    "have occurred"
                ),
            }],
        }
