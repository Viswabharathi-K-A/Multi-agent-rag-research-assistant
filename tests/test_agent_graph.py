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
    structured = Mock()
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

    case["structured"].invoke.side_effect = decide
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

    case["structured"].invoke.side_effect = decide
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
