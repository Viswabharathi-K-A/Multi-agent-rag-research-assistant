
import json
from typing import Literal

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

from app.agents.citations import normalize_document_citations, validate_document_citations, validate_web_citations
from app.agents.state import AgentName, ResearchState, RetrievalMode, SourcePolicy
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
    required_agents: list[AgentName] = Field(default_factory=list, description="Specialists explicitly requested by the user; empty when none are explicitly requested")
    source_policy: SourcePolicy = Field(default="unrestricted", description="Global explicit source restriction: documents for corpus-only/no-web/offline requests, web for web-only requests, otherwise unrestricted")


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
- On the first decision, extract the original request's global source_policy.
  Persisted source_policy is authoritative for every worker, not just Research.
  Do not interpret Research's default documents mode as a global no-web request.
- On the first decision, extract explicitly requested specialists into required_agents.
  Do not treat ordinary verbs such as 'summarize', quoted text, or negated requests
  as explicit specialist requests. Persisted required_agents are authoritative.
- Before finishing, examine pending_agents and failed_agents. Delegate pending
  requested specialists as appropriate; report failed requested work honestly.
- Never invent research results or citations.
- If a worker fails, consider an alternative.
- Failed results contain failure details, not usable findings or sources. Use
  only successful results as evidence for final answers. If no successful
  evidence answers the request, delegate appropriate work or explain the failure.
- If the task is complete, select "finish".
- When finishing, provide a grounded final answer.
- Keep the final answer concise by default: aim for about 150-250 words for
  substantive questions, and much less for simple questions. Follow the user's
  requested length and detail instead when specified; do not truncate necessary
  code, evidence, or qualifications to meet a word target.
- Answer directly, combining successful findings without repeating each worker's
  report, source appendix, or orchestration history. Use brief Markdown headings
  (## or ###) only when multiple topics need separation, short lists where useful,
  and fenced code blocks for code. Simple answers need no forced headings.
- Source restrictions in allowed_domains apply to all web evidence and cannot
  be broadened on failure. A third-party source is not an official source merely
  because it discusses official documentation. Report missing evidence honestly.
- Never introduce an unsupplied source URL in a delegated instruction or final
  answer. Keep web URLs distinct from document source_id values.
- Delegate with search keywords and hostname restrictions, not example URLs,
  guessed paths, or fragments. Copy a URL only when it already appears in supplied
  evidence. A worker's prose claiming that another agent ran or searched is not
  execution evidence; inspect result.agent and tool traces instead.

Final-answer citations:
- Cite supported claims using exact source_id values from completed_results.sources.
- Put each document source_id in its own brackets, preserving every character.
  For example: [raft.pdf:p5:c4] [raft.pdf:p5:c5]. These are format examples;
  use only IDs actually supplied in the results.
- Never compress IDs into ranges such as [raft.pdf:p5:c4-c5], or combine IDs
  inside one bracket pair such as [raft.pdf:p5:c4, raft.pdf:p5:c5].
- Paper titles and PDF page references may accompany exact IDs but must not
  replace them. Cite web sources as [exact URL], one per bracket pair. Their
  source_id is the supplied exact URL; copy it unchanged so the UI can link it.
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


def required_agent_status(state: ResearchState) -> tuple[list[AgentName], list[AgentName]]:
    """Derive unattempted and unsuccessful requirements from existing results."""
    attempted = {result.get("agent") for result in state.get("results", [])}
    successful = {result.get("agent") for result in state.get("results", []) if result.get("success")}
    required = state.get("required_agents", [])
    return ([agent for agent in required if agent not in attempted],
            [agent for agent in required if agent in attempted and agent not in successful])


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
    if "required_agents" in state:
        context["required_agents"] = state["required_agents"]
        context["pending_agents"], context["failed_agents"] = required_agent_status(state)
    if "source_policy" in state:
        context["source_policy"] = state["source_policy"]

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
    required_agents = list(dict.fromkeys(state.get("required_agents", decision.required_agents)))
    source_policy = state.get("source_policy", decision.source_policy)
    domains = normalize_domains(state.get("allowed_domains") or decision.allowed_domains)
    planning_state = {**state, "required_agents": required_agents, "allowed_domains": domains,
                      "source_policy": source_policy}
    pending, failed = required_agent_status(planning_state)
    reconsideration_trace = []
    if decision.next_agent == "finish" and pending:
        reconsideration_trace.append({
            "node": "supervisor", "action": "completion_reconsideration",
            "detail": f"Requested specialists have not run: {', '.join(pending)}",
            "provider": provider, "model": model,
            "reason": "One additional decision before accepting premature completion",
        })
        decision = await structured_llm.ainvoke([
            SystemMessage(content=SUPERVISOR_PROMPT),
            HumanMessage(content=build_supervisor_context(planning_state)),
            HumanMessage(content="Your finish decision left pending requested specialists. "
                         "Reconsider once and choose the appropriate next worker, or explain why work cannot continue."),
        ])

    if decision.next_agent == "research" and source_policy != "unrestricted":
        decision.retrieval_mode = source_policy

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
        "required_agents": required_agents,
        "source_policy": source_policy,
        "trace": reconsideration_trace + [trace_event],
    }
    if domains:
        update["allowed_domains"] = domains
        trace_event["detail"] += f" (allowed_domains={domains})"
    if decision.next_agent == "research" and decision.search_query.strip():
        trace_event["detail"] += f" (search_query={decision.search_query.strip()})"

    if decision.next_agent == "finish":
        update["current_task"] = None
        if pending:
            update["final_answer"] = (
                "The requested workflow is incomplete. Specialists not run: "
                + ", ".join(pending) + "."
            )
            if failed:
                update["final_answer"] += " Requested specialists that failed: " + ", ".join(failed) + "."
            return update
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
        if failed:
            # Replace completion claims with a factual status; worker results remain available.
            update["final_answer"] = "Requested work could not be completed: " + ", ".join(failed) + " failed."
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
