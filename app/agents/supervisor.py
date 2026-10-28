
import json
from typing import Literal

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

from app.agents.citations import normalize_document_citations, validate_document_citations, validate_web_citations
from app.agents.state import ResearchState, RetrievalMode
from app.config import get_settings
from app.services.tavily_mcp import normalize_domains, url_matches_domains


class SupervisorDecision(BaseModel):
    next_agent: Literal[
        "research", "code", "summary", "finish"
    ]
    instruction: str = Field(
        description="Specific task for the selected agent"
    )
    reason: str = Field(
        description="Why this agent is needed next and, for research, why these sources are appropriate"
    )
    retrieval_mode: RetrievalMode = Field(
        default="documents",
        description="Research evidence source: documents, web, or both; ignored for other agents",
    )
    final_answer: str = Field(
        default="",
        description="Answer if the workflow is complete"
    )
    search_query: str = Field(default="", description="Concise keyword query for Research web search, not the full task instruction")
    allowed_domains: list[str] = Field(default_factory=list, description="Source hostname restrictions requested by the user, e.g. docs.python.org for official Python docs; empty when unrestricted")


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
- Failed results contain failure details, not usable findings or sources. Use
  only successful results as evidence for final answers. If no successful
  evidence answers the request, delegate appropriate work or explain the failure.
- If the task is complete, select "finish".
- When finishing, provide a grounded final answer.
- Source restrictions in allowed_domains apply to all web evidence and cannot
  be broadened on failure. A third-party source is not an official source merely
  because it discusses official documentation. Report missing evidence honestly.
- Never introduce an unsupplied source URL in a delegated instruction or final
  answer. Keep web URLs distinct from document source_id values.

Final-answer citations:
- Cite supported claims using exact source_id values from completed_results.sources.
- Put each document source_id in its own brackets, preserving every character.
  For example: [raft.pdf:p5:c4] [raft.pdf:p5:c5]. These are format examples;
  use only IDs actually supplied in the results.
- Never compress IDs into ranges such as [raft.pdf:p5:c4-c5], or combine IDs
  inside one bracket pair such as [raft.pdf:p5:c4, raft.pdf:p5:c5].
- Paper titles and PDF page references may accompany exact IDs but must not
  replace them. Cite web sources using their exact supplied URLs.
- Keep citations alongside the claims they support. If support is missing,
  acknowledge the limitation instead of inventing an ID or source.

Research source selection:
- Set retrieval_mode whenever selecting the research agent, and explain the
  source choice in reason.
- For web or both, provide search_query as concise search keywords rather than
  the full delegated instruction. Populate allowed_domains for explicit domain
  restrictions or official-source requests whose official host is known. Do not
  guess an official host when uncertain; explain the uncertainty instead.
- Use "documents" for questions about the provided corpus. This is the default
  for requests without an explicit source preference or need for current facts.
- Use "web" for explicit web searches or current information outside the corpus.
- Use "both" when the request needs document evidence and external information,
  such as comparing provided documentation with current practices.
- Respect explicit source restrictions: "only the provided documents" means
  documents; "web only" means web. Never broaden those restrictions on failure.
- If documents lack sufficient evidence, you may delegate web research when
  the user's source restrictions permit it. Do not claim missing evidence exists.
- For code, summary, or finish decisions, retrieval_mode has no effect.
"""


def build_supervisor_context(state: ResearchState) -> str:
    """Expose successful evidence and failed-task details without changing state."""

    completed_results = []
    for result in state.get("results", []):
        if result.get("success"):
            completed_results.append(result)
        else:
            completed_results.append({
                "agent": result.get("agent"),
                "instruction": result.get("instruction"),
                "success": False,
                "error": result.get("error"),
                "content": "",
            })

    context = {
        "user_query": state["user_query"],
        "completed_results": completed_results,
        "iteration": state.get("iteration", 0),
        "max_iterations": state.get(
            "max_iterations", 8
        ),
    }
    if state.get("allowed_domains"):
        context["allowed_domains"] = state["allowed_domains"]

    return json.dumps(context, ensure_ascii=False)


async def supervisor_node(state: ResearchState) -> dict:
    """Choose the next agent using an LLM."""

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

    settings = get_settings()

    # Use the shared provider factory only when another decision is needed.
    from app.llm import get_agent_llm

    llm = get_agent_llm("supervisor")
    structured_llm = llm.with_structured_output(
        SupervisorDecision
    )

    decision = await structured_llm.ainvoke([
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
        "detail": (
            f"{decision.instruction} (retrieval_mode={decision.retrieval_mode})"
            if decision.next_agent == "research" else decision.instruction
        ),
        "provider": provider,
        "model": model,
        "reason": (
            "Supervisor uses its configured provider for capability-based "
            "delegation, evidence review, and final synthesis. "
            f"Decision: {decision.reason}"
        ),
    }

    update = {
        "iteration": iteration + 1,
        "next_agent": decision.next_agent,
        "trace": [trace_event],
    }
    domains = normalize_domains(state.get("allowed_domains") or decision.allowed_domains)
    if domains:
        update["allowed_domains"] = domains
        trace_event["detail"] += f" (allowed_domains={domains})"
    if decision.next_agent == "research" and decision.search_query.strip():
        trace_event["detail"] += f" (search_query={decision.search_query.strip()})"

    if decision.next_agent == "finish":
        update["current_task"] = None
        sources = []
        for result in state.get("results", []):
            if result.get("success"):
                sources.extend(source for source in result.get("sources", [])
                               if source.get("source_kind") != "web" or url_matches_domains(source["url"], domains))
        update["final_answer"] = normalize_document_citations(decision.final_answer, sources)
        try:
            validate_document_citations(update["final_answer"], sources)
            validate_web_citations(update["final_answer"], sources)
        except ValueError as exc:
            update["final_answer"] = (
                "I could not produce a final answer with valid source citations. "
                "Please review the retrieved sources."
            )
            update["trace"].append({
                "node": "supervisor",
                "action": "citation_validation_failed",
                "detail": str(exc),
                "provider": None,
                "model": None,
                "reason": "Document IDs and web URLs must match evidence from successful workers",
            })
    else:
        update["current_task"] = {
            "agent": decision.next_agent,
            "instruction": decision.instruction,
        }
        if decision.next_agent == "research":
            update["current_task"]["retrieval_mode"] = decision.retrieval_mode
            if decision.search_query.strip():
                update["current_task"]["search_query"] = decision.search_query.strip()
        if domains:
            update["current_task"]["allowed_domains"] = domains

    return update
