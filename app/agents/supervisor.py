
import json
from typing import Literal

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

from app.agents.state import ResearchState
from app.config import get_settings


class SupervisorDecision(BaseModel):
    next_agent: Literal[
        "research", "code", "summary", "finish"
    ]
    instruction: str = Field(
        description="Specific task for the selected agent"
    )
    reason: str = Field(
        description="Why this agent is needed next"
    )
    final_answer: str = Field(
        default="",
        description="Answer if the workflow is complete"
    )


SUPERVISOR_PROMPT = """
You are the supervisor of a multi-agent RAG system.

Available agents:
- research: Search documents, retrieve evidence,
  and perform external research.
- code: Analyze, explain, and generate code.
- summary: Synthesize research and agent outputs.

Your responsibilities:
1. Analyze the original user request.
2. Examine completed agent results.
3. Select the next necessary agent.
4. Give that agent a specific instruction.
5. Avoid unnecessary or repeated delegation.
6. Finish when the request has been fulfilled.

Rules:
- Base decisions on the actual request and evidence.
- Never invent research results or citations.
- If a worker fails, consider an alternative.
- If the task is complete, select "finish".
- When finishing, provide a grounded final answer.
"""


def build_supervisor_context(state: ResearchState) -> str:
    """Prepare information for the supervisor LLM."""

    context = {
        "user_query": state["user_query"],
        "completed_results": state.get("results", []),
        "pending_tasks": state.get("tasks", []),
        "iteration": state.get("iteration", 0),
        "max_iterations": state.get(
            "max_iterations", 8
        ),
    }

    return json.dumps(context, ensure_ascii=False)


def supervisor_node(state: ResearchState) -> dict:
    """Choose the next agent using an LLM."""

    settings = get_settings()

    # Provider/model creation will be implemented
    # in the shared LLM configuration module.
    from app.llm import get_agent_llm

    llm = get_agent_llm("supervisor")
    structured_llm = llm.with_structured_output(
        SupervisorDecision
    )

    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 8)

    if iteration >= max_iterations:
        return {
            "next_agent": "finish",
            "final_answer": (
                "Execution stopped at the iteration limit. "
                "The available results may be incomplete."
            ),
            "trace": [{
                "node": "supervisor",
                "action": "limit_reached",
                "detail": "Maximum supervisor iterations reached",
                "provider": None,
                "model": None,
                "reason": "Execution safety limit",
            }],
        }

    decision = structured_llm.invoke([
        SystemMessage(content=SUPERVISOR_PROMPT),
        HumanMessage(
            content=build_supervisor_context(state)
        ),
    ])

    provider = settings.supervisor_provider
    model = settings.supervisor_model

    trace_event = {
        "node": "supervisor",
        "action": (
            "finish" if decision.next_agent == "finish"
            else "delegate"
        ),
        "detail": decision.instruction,
        "provider": provider,
        "model": model,
        "reason": decision.reason,
    }

    update = {
        "iteration": iteration + 1,
        "next_agent": decision.next_agent,
        "trace": [trace_event],
    }

    if decision.next_agent == "finish":
        update["current_task"] = None
        update["final_answer"] = decision.final_answer
    else:
        update["current_task"] = {
            "agent": decision.next_agent,
            "instruction": decision.instruction,
        }

    return update
