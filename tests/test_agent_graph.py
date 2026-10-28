"""Run the real LangGraph and workers with mocked external boundaries."""

import json
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app import llm
from app.agents import code, research, summary, supervisor
from app.agents.agents import build_agent_graph
from app.config import Settings


@pytest.fixture
def case(monkeypatch):
    settings = Settings(_env_file=None, research_timeout_seconds=5,
                        supervisor_provider="openai", supervisor_model="mock-supervisor")
    chunk = Document(page_content="Leader election evidence", metadata={
        "chunk_id": "raft.pdf:p6:c1", "document_id": "document:raft.pdf",
        "source": "raft.pdf", "title": "raft", "page": 6,
        "source_kind": "document", "start_index": 0,
    })
    documents = Mock(return_value=[chunk])
    web = AsyncMock(side_effect=AssertionError("Unexpected web request"))
    models = {role: Mock(ainvoke=AsyncMock(return_value=AIMessage(
        content=f"{role} findings [raft.pdf:p6:c1]")))
        for role in ("research", "code", "summary")}
    models["code"].bind_tools.return_value = models["code"]
    structured = Mock(ainvoke=AsyncMock())
    supervisor_model = Mock()
    supervisor_model.with_structured_output.return_value = structured
    models["supervisor"] = supervisor_model
    factory = Mock(side_effect=lambda role: models[role])
    monkeypatch.setattr(llm, "get_agent_llm", factory)
    monkeypatch.setattr(supervisor, "get_settings", lambda: settings)
    for module in (research, code, summary):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
        monkeypatch.setattr(module, "get_agent_llm", factory)
        monkeypatch.setattr(module, "get_agent_provider_info", lambda role: (
            "openai" if role == "code" else "google", f"mock-{role}"))
    monkeypatch.setattr(research, "retrieve_documents", documents)
    monkeypatch.setattr(summary, "retrieve_documents", documents)
    monkeypatch.setattr(research, "search_web", web)
    monkeypatch.setattr(code, "search_web", web)
    return {"models": models, "structured": structured, "documents": documents,
            "web": web, "contexts": [], "state": {
                "user_query": "Explain Raft and propose code, then summarize",
                "iteration": 0, "max_iterations": 8}}


@pytest.mark.asyncio
async def test_all_workers_run_and_preserve_evidence_and_trace(case):
    def decide(messages):
        context = json.loads(messages[1].content)
        case["contexts"].append(context)
        results = context["completed_results"]
        assert all(result["success"] for result in results)
        completed = {result["agent"] for result in results}
        for agent in ("research", "code", "summary"):
            if agent not in completed:
                return supervisor.SupervisorDecision(
                    next_agent=agent, instruction=f"Perform {agent} task",
                    reason=f"{agent} work is still needed")
        return supervisor.SupervisorDecision(
            next_agent="finish", instruction="", reason="All requested work succeeded",
            final_answer=results[-1]["content"])

    case["structured"].ainvoke.side_effect = decide
    output = await build_agent_graph().ainvoke(case["state"])

    assert [result["agent"] for result in output["results"]] == ["research", "code", "summary"]
    assert [len(context["completed_results"]) for context in case["contexts"]] == [0, 1, 2, 3]
    assert output["next_agent"] == "finish" and output["current_task"] is None
    assert output["iteration"] == 4
    assert "[raft.pdf:p6:c1]" in output["final_answer"]
    sources = output["results"][0]["sources"]
    assert sources[0]["content"] == "Leader election evidence"
    assert sources[0]["metadata"]["page"] == 6
    assert all(result["sources"] == sources for result in output["results"])
    actions = [(event["node"], event["action"]) for event in output["trace"]]
    assert actions.count(("supervisor", "delegate")) == 3
    assert actions.count(("supervisor", "finish")) == 1
    for agent in ("research", "code", "summary"):
        assert actions.count((agent, "llm_started")) == 1
        case["models"][agent].ainvoke.assert_awaited_once()
    calls = [event for event in output["trace"]
             if event["node"] == "supervisor" or event["action"] == "llm_started"]
    assert {event["provider"] for event in calls} == {"openai", "google"}
    assert all(event["model"] and event["reason"] for event in calls)
    case["documents"].assert_called_once()
    case["web"].assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("recover", [True, False])
async def test_graph_handles_skipped_explicit_summary(case, recover):
    def decide(messages):
        context = json.loads(messages[1].content)
        completed = {result["agent"] for result in context["completed_results"]}
        if not completed:
            return supervisor.SupervisorDecision(
                next_agent="research", instruction="Find Raft evidence", reason="Evidence needed",
                required_agents=["research", "code", "summary"])
        if "code" not in completed:
            return supervisor.SupervisorDecision(
                next_agent="code", instruction="Explain implementation", reason="Code needed")
        if len(messages) == 3 and recover:
            assert context["pending_agents"] == ["summary"]
            return supervisor.SupervisorDecision(
                next_agent="summary", instruction="Synthesize findings", reason="Explicitly requested")
        return supervisor.SupervisorDecision(
            next_agent="finish", instruction="", reason="Done",
            final_answer="Findings [raft.pdf:p6:c1]")

    case["state"]["user_query"] = "Use Research, Code, and Summary agents for Raft"
    case["structured"].ainvoke.side_effect = decide
    output = await build_agent_graph().ainvoke(case["state"])
    assert [result["agent"] for result in output["results"]] == (
        ["research", "code", "summary"] if recover else ["research", "code"])
    assert output["required_agents"] == ["research", "code", "summary"]
    assert output["next_agent"] == "finish"
    assert case["structured"].ainvoke.await_count == (5 if recover else 4)
    assert sum(event["action"] == "completion_reconsideration" for event in output["trace"]) == 1
    assert ("incomplete" in output["final_answer"]) == (not recover)
    case["web"].assert_not_awaited()


@pytest.mark.asyncio
async def test_required_worker_failure_cannot_be_reported_as_success(case):
    case["models"]["summary"].ainvoke.side_effect = RuntimeError("Private error")
    case["structured"].ainvoke.side_effect = [
        supervisor.SupervisorDecision(next_agent="summary", instruction="Summarize Raft",
                                      reason="Requested", required_agents=["summary"]),
        supervisor.SupervisorDecision(next_agent="finish", instruction="", reason="Done",
                                      final_answer="All requested work succeeded"),
    ]
    output = await build_agent_graph().ainvoke(case["state"])
    assert output["final_answer"] == "Requested work could not be completed: summary failed."
    assert output["results"][0]["success"] is False
    assert case["structured"].ainvoke.await_count == 2
    context = json.loads(case["structured"].ainvoke.call_args.args[0][1].content)
    assert context["pending_agents"] == []
    assert context["failed_agents"] == ["summary"]


@pytest.mark.asyncio
@pytest.mark.parametrize("agent", ["research", "code", "summary"])
async def test_worker_model_failure_returns_to_supervisor_and_finishes(case, agent):
    case["models"][agent].ainvoke.side_effect = RuntimeError("Private provider error")

    def decide(messages):
        context = json.loads(messages[1].content)
        case["contexts"].append(context)
        results = context["completed_results"]
        if not results:
            return supervisor.SupervisorDecision(
                next_agent=agent, instruction="Perform delegated task",
                reason="This specialist is needed")
        assert len(results) == 1
        assert results[0]["agent"] == agent and not results[0]["success"]
        assert results[0]["error"] and not results[0]["content"]
        return supervisor.SupervisorDecision(
            next_agent="finish", instruction="", reason="Report the worker failure honestly",
            final_answer="The requested task could not be completed.")

    case["structured"].ainvoke.side_effect = decide
    output = await build_agent_graph().ainvoke(case["state"])

    assert len(case["contexts"]) == 2
    assert output["next_agent"] == "finish" and output["iteration"] == 2
    assert output["final_answer"] == "The requested task could not be completed."
    assert "Private provider error" not in json.dumps(output)
    assert len(output["results"]) == 1 and not output["results"][0]["success"]
    if agent != "code":
        assert output["results"][0]["sources"][0]["source_id"] == "raft.pdf:p6:c1"
    actions = [(event["node"], event["action"]) for event in output["trace"]]
    assert actions.count((agent, f"{agent}_failed")) == 1
    assert actions[0] == ("supervisor", "delegate")
    assert actions[-1] == ("supervisor", "finish")
    case["web"].assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("invented_final_url", [False, True])
async def test_web_workflow_preserves_domains_and_bounds_citation_repairs(case, invented_final_url):
    url = "https://example.com/reference"
    case["web"].side_effect = None
    case["web"].return_value = ("tavily_search", [{
        "source_id": "web-1", "url": url, "title": "Reference", "content": "Evidence", "metadata": {},
    }])
    case["models"]["research"].ainvoke.side_effect = [
        AIMessage(content="Missing citations"), AIMessage(content=f"Research {url}"),
    ]
    case["models"]["code"].ainvoke.return_value = AIMessage(content=f"Code findings {url}")
    case["models"]["summary"].ainvoke.side_effect = [
        AIMessage(content="Missing citations"), AIMessage(content=f"Summary {url}"),
    ]

    def decide(messages):
        context = json.loads(messages[1].content)
        completed = context["completed_results"]
        if completed:
            assert context["allowed_domains"] == ["example.com"]
            assert all(result["success"] for result in completed)
        if len(completed) < 3:
            return supervisor.SupervisorDecision(
                next_agent=("research", "code", "summary")[len(completed)],
                instruction="Explain the official reference", reason="Requested specialist work",
                retrieval_mode="web", search_query="concise reference query", allowed_domains=["example.com"])
        return supervisor.SupervisorDecision(
            next_agent="finish", instruction="", reason="All specialists completed",
            final_answer="Final https://example.com/invented" if invented_final_url else f"Final {url}")

    case["structured"].ainvoke.side_effect = decide
    output = await build_agent_graph().ainvoke(case["state"])

    assert output["allowed_domains"] == ["example.com"]
    assert all(result["success"] for result in output["results"])
    case["web"].assert_awaited_once_with("concise reference query", allowed_domains=["example.com"])
    case["documents"].assert_not_called()
    assert case["models"]["research"].ainvoke.await_count == 2
    assert case["models"]["summary"].ainvoke.await_count == 2
    assert case["models"]["code"].ainvoke.await_count == 1
    assert sum(event["action"] == "citation_repair_started" for event in output["trace"]) == 2
    if invented_final_url:
        assert output["trace"][-1]["action"] == "citation_validation_failed"
        assert "valid source citations" in output["final_answer"]
    else:
        assert output["final_answer"] == f"Final {url}"
