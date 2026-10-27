"""Offline supervisor tests; model construction and generation are mocked."""

import json
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app import llm
from app.agents import supervisor
from app.config import Settings


@pytest.fixture
def case(monkeypatch):
    settings = Settings(_env_file=None, supervisor_provider="openai",
                        supervisor_model="mock-supervisor")
    structured = Mock(ainvoke=AsyncMock())
    model = Mock()
    model.with_structured_output.return_value = structured
    factory = Mock(return_value=model)
    monkeypatch.setattr(supervisor, "get_settings", lambda: settings)
    monkeypatch.setattr(llm, "get_agent_llm", factory)
    return {"state": {"user_query": "Explain Raft", "iteration": 2,
                      "max_iterations": 8},
            "structured": structured, "model": model, "factory": factory}


def test_context_defaults():
    context = json.loads(supervisor.build_supervisor_context({"user_query": "Explain Raft"}))
    assert context == {"user_query": "Explain Raft", "completed_results": [],
                       "iteration": 0, "max_iterations": 8}


@pytest.mark.asyncio
async def test_worker_failure_and_sources_reach_model(case):
    result = {"agent": "research", "instruction": "Find election evidence",
              "content": "", "success": False, "error": "Web retrieval failed",
              "sources": [{"source_id": "raft.pdf:p6:c1", "content": "Retained evidence"}]}
    task = {"agent": "summary", "instruction": "Summarize retained evidence"}
    case["state"]["results"] = [result]
    case["structured"].ainvoke.return_value = supervisor.SupervisorDecision(
        next_agent="summary", instruction=task["instruction"], reason="Use retained evidence")

    output = await supervisor.supervisor_node(case["state"])

    messages = case["structured"].ainvoke.call_args.args[0]
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == supervisor.SUPERVISOR_PROMPT
    assert isinstance(messages[1], HumanMessage)
    assert json.loads(messages[1].content) == {
        "user_query": "Explain Raft", "completed_results": [result],
        "iteration": 2, "max_iterations": 8,
    }
    assert output["next_agent"] == "summary"
    assert case["state"]["results"] == [result]


@pytest.mark.asyncio
@pytest.mark.parametrize("agent,mode", [
    ("research", "documents"), ("research", "web"), ("research", "both"),
    ("code", "both"), ("summary", "both"),
])
async def test_delegation_preserves_task_and_trace(case, agent, mode):
    decision = supervisor.SupervisorDecision(
        next_agent=agent, instruction="Review relevant evidence",
        reason="This specialist is needed for the request", retrieval_mode=mode)
    case["structured"].ainvoke.return_value = decision

    output = await supervisor.supervisor_node(case["state"])

    expected_task = {"agent": agent, "instruction": decision.instruction}
    if agent == "research":
        expected_task["retrieval_mode"] = mode
    assert output["current_task"] == expected_task
    assert output["next_agent"] == agent
    assert output["iteration"] == 3
    assert "results" not in output
    assert "final_answer" not in output
    assert len(output["trace"]) == 1
    trace = output["trace"][0]
    assert trace["node"] == "supervisor" and trace["action"] == "delegate"
    assert trace["provider"] == "openai" and trace["model"] == "mock-supervisor"
    assert "capability-based" in trace["reason"]
    assert decision.reason in trace["reason"]
    assert decision.instruction in trace["detail"]
    if agent == "research":
        assert f"retrieval_mode={mode}" in trace["detail"]
    case["factory"].assert_called_once_with("supervisor")
    case["model"].with_structured_output.assert_called_once_with(supervisor.SupervisorDecision)
    case["structured"].ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_finish_clears_task_and_preserves_answer_citation(case):
    answer = "Raft election findings [raft.pdf:p6:c1]"
    case["state"]["current_task"] = {"agent": "research", "instruction": "Find evidence"}
    case["structured"].ainvoke.return_value = supervisor.SupervisorDecision(
        next_agent="finish", instruction="", reason="Evidence answers the question",
        final_answer=answer)

    output = await supervisor.supervisor_node(case["state"])

    assert output["next_agent"] == "finish"
    assert output["current_task"] is None
    assert output["final_answer"] == answer
    assert output["iteration"] == 3
    trace = output["trace"][0]
    assert trace["action"] == "finish"
    assert trace["provider"] == "openai" and trace["model"] == "mock-supervisor"
    assert "capability-based" in trace["reason"]
    assert "Evidence answers the question" in trace["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("iteration", [8, 9])
async def test_iteration_limit_stops_without_generation(case, iteration):
    case["state"]["iteration"] = iteration

    output = await supervisor.supervisor_node(case["state"])

    assert output["next_agent"] == "finish"
    assert "incomplete" in output["final_answer"]
    assert "iteration" not in output
    trace = output["trace"][0]
    assert trace["action"] == "limit_reached"
    assert trace["provider"] is None and trace["model"] is None
    case["structured"].ainvoke.assert_not_called()
