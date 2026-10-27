"""Offline supervisor tests; model construction and generation are mocked."""

import json
from copy import deepcopy
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
async def test_worker_failure_details_reach_model_without_failed_evidence(case):
    result = {"agent": "research", "instruction": "Find election evidence",
              "content": "Rejected findings", "success": False, "error": "Web retrieval failed",
              "sources": [{"source_id": "raft.pdf:p6:c1", "content": "Retained evidence"}]}
    task = {"agent": "summary", "instruction": "Retrieve documents and summarize"}
    case["state"]["results"] = [result]
    original = deepcopy(case["state"])
    case["structured"].ainvoke.return_value = supervisor.SupervisorDecision(
        next_agent="summary", instruction=task["instruction"], reason="Try document summarization")

    output = await supervisor.supervisor_node(case["state"])

    messages = case["structured"].ainvoke.call_args.args[0]
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == supervisor.SUPERVISOR_PROMPT
    assert isinstance(messages[1], HumanMessage)
    assert json.loads(messages[1].content) == {
        "user_query": "Explain Raft", "completed_results": [{
            "agent": "research", "instruction": "Find election evidence",
            "success": False, "error": "Web retrieval failed", "content": "",
        }],
        "iteration": 2, "max_iterations": 8,
    }
    assert output["next_agent"] == "summary"
    assert case["state"] == original
    case["structured"].ainvoke.assert_awaited_once()


def test_mixed_context_preserves_successful_evidence_and_filters_failed_evidence():
    successful = {"agent": "research", "instruction": "Find evidence", "success": True,
                  "content": "Finding [raft.pdf:p5:c4]", "error": None,
                  "sources": [{"source_id": "raft.pdf:p5:c4", "source_kind": "document",
                               "content": "Successful evidence"}]}
    failed = {"agent": "code", "instruction": "Analyze code", "success": False,
              "content": "Rejected output", "error": "Code operation failed",
              "sources": [{"source_id": "failed.pdf:p1:c1", "source_kind": "document",
                           "content": "Failed evidence"}]}
    state = {"user_query": "Explain Raft", "results": [successful, failed]}
    original = deepcopy(state)

    context = json.loads(supervisor.build_supervisor_context(state))

    assert context["completed_results"] == [successful, {
        "agent": "code", "instruction": "Analyze code", "success": False,
        "error": "Code operation failed", "content": "",
    }]
    assert state == original


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
@pytest.mark.parametrize("document_refs", [
    [("raft.pdf:p5:c4", 5), ("raft.pdf:p5:c5", 5)],
    [("raft.pdf:p4:c1", 4), ("raft.pdf:p8:c7", 8)],
])
async def test_finish_preserves_separate_citations_and_source_context(case, document_refs):
    sources = [{"source_id": source_id, "source_kind": "document",
                "source": "raft.pdf", "title": "Raft", "content": "Election evidence",
                "metadata": {"chunk_id": source_id, "page": page}}
               for source_id, page in document_refs]
    url = "https://example.com/raft?section=election&version=1"
    sources.append({"source_id": "web-1", "source_kind": "web", "url": url,
                    "title": "Technical reference", "content": "External evidence", "metadata": {}})
    answer = "Raft election findings " + " ".join(f"[{source_id}]" for source_id, _ in document_refs)
    answer += f"\nTechnical reference: {url}"
    result = {"agent": "research", "instruction": "Find evidence", "content": answer,
              "success": True, "error": None, "sources": sources}
    case["state"]["results"] = [result]
    case["state"]["current_task"] = {"agent": "research", "instruction": "Find evidence"}
    case["structured"].ainvoke.return_value = supervisor.SupervisorDecision(
        next_agent="finish", instruction="", reason="Evidence answers the question",
        final_answer=answer)

    output = await supervisor.supervisor_node(case["state"])

    assert output["next_agent"] == "finish"
    assert output["current_task"] is None
    assert output["final_answer"] == answer
    messages = case["structured"].ainvoke.call_args.args[0]
    assert messages[0].content == supervisor.SUPERVISOR_PROMPT
    context = json.loads(messages[1].content)
    assert context["completed_results"] == [result]
    assert case["state"]["results"] == [result]
    assert "results" not in output
    assert output["iteration"] == 3
    trace = output["trace"][0]
    assert trace["action"] == "finish"
    assert trace["provider"] == "openai" and trace["model"] == "mock-supervisor"
    assert "capability-based" in trace["reason"]
    assert "Evidence answers the question" in trace["reason"]


@pytest.mark.asyncio
async def test_finish_normalizes_combined_successful_document_citations_without_retry(case):
    sources = [{"source_kind": "document", "source_id": source_id,
                "content": "Election evidence"}
               for source_id in ("raft.pdf:p5:c4", "raft.pdf:p5:c5")]
    case["state"]["results"] = [{
        "agent": "research", "success": True, "content": "Research findings", "sources": sources,
    }]
    original = deepcopy(case["state"])
    answer = "Finding [raft.pdf:p5:c4, raft.pdf:p5:c5]."
    decision = supervisor.SupervisorDecision(
        next_agent="finish", instruction="", reason="Successful evidence answers the query",
        final_answer=answer)
    case["structured"].ainvoke.return_value = decision

    output = await supervisor.supervisor_node(case["state"])

    assert output["final_answer"] == "Finding [raft.pdf:p5:c4] [raft.pdf:p5:c5]."
    assert output["next_agent"] == "finish" and output["current_task"] is None
    assert [trace["action"] for trace in output["trace"]] == ["finish"]
    assert case["state"] == original
    assert decision.final_answer == answer
    case["structured"].ainvoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [
    "Claim [raft.pdf:p5:c4-c5]",
    "Claim [raft.pdf:p5:c4–c5]",
    "Claim [raft.pdf:p5:c4, raft.pdf:p99:c99]",
    "Claim [raft.pdf:p5:c4] and invented [raft.pdf:p99:c99]",
    "Claim without citations",
    "Web only https://example.com/ref",
    "",
])
async def test_finish_rejects_invalid_document_citations_without_retry(case, answer):
    sources = [{"source_kind": "document", "source_id": source_id,
                "source": "raft.pdf", "content": "Evidence", "metadata": {"page": 5}}
               for source_id in ("raft.pdf:p5:c4", "raft.pdf:p5:c5")]
    result = {"agent": "research", "success": True, "content": "Finding [raft.pdf:p5:c4]",
              "sources": sources}
    case["state"]["results"] = [result]
    case["structured"].ainvoke.return_value = supervisor.SupervisorDecision(
        next_agent="finish", instruction="", reason="Task complete", final_answer=answer)

    output = await supervisor.supervisor_node(case["state"])

    assert output["next_agent"] == "finish" and output["current_task"] is None
    assert output["iteration"] == 3
    assert output["final_answer"] == (
        "I could not produce a final answer with valid document citations. "
        "Please review the retrieved sources."
    )
    assert "results" not in output and case["state"]["results"] == [result]
    assert [trace["action"] for trace in output["trace"]] == ["finish", "citation_validation_failed"]
    failure = output["trace"][-1]
    assert failure["provider"] is None and failure["model"] is None
    case["structured"].ainvoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("result,answer", [
    ({"success": True, "content": "Code explanation", "sources": []}, "Self-contained code explanation"),
    ({"success": True, "content": "Web finding", "sources": [
        {"source_kind": "web", "source_id": "web-1", "url": "https://example.com/ref"}]},
     "Web finding https://example.com/ref"),
    ({"success": False, "content": "", "sources": [
        {"source_kind": "document", "source_id": "raft.pdf:p5:c4"}]},
     "The requested task could not be completed."),
])
async def test_finish_without_successful_document_evidence_preserves_answer(case, result, answer):
    case["state"]["results"] = [result]
    case["structured"].ainvoke.return_value = supervisor.SupervisorDecision(
        next_agent="finish", instruction="", reason="Task complete", final_answer=answer)

    output = await supervisor.supervisor_node(case["state"])

    assert output["final_answer"] == answer
    assert [trace["action"] for trace in output["trace"]] == ["finish"]


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [
    "Claim [raft.pdf:p5:c4]",
    "Claim [raft.pdf:p5:c4, failed.pdf:p1:c1]",
])
async def test_finish_does_not_accept_ids_only_retained_by_failed_workers(case, answer):
    case["state"]["results"] = [{"success": False, "sources": [
        {"source_kind": "document", "source_id": "raft.pdf:p5:c4"},
        {"source_kind": "document", "source_id": "failed.pdf:p1:c1"}]}]
    case["structured"].ainvoke.return_value = supervisor.SupervisorDecision(
        next_agent="finish", instruction="", reason="Task complete",
        final_answer=answer)

    output = await supervisor.supervisor_node(case["state"])

    assert "valid document citations" in output["final_answer"]
    assert output["trace"][-1]["action"] == "citation_validation_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("iteration", [8, 9])
async def test_iteration_limit_stops_without_settings_or_model(case, monkeypatch, iteration):
    case["state"]["iteration"] = iteration
    settings = Mock(side_effect=ValueError("Settings must not be loaded at the limit"))
    monkeypatch.setattr(supervisor, "get_settings", settings)
    case["factory"].side_effect = ValueError("Model must not be constructed at the limit")

    output = await supervisor.supervisor_node(case["state"])

    assert output["next_agent"] == "finish"
    assert "incomplete" in output["final_answer"]
    assert "iteration" not in output
    trace = output["trace"][0]
    assert trace["action"] == "limit_reached"
    assert trace["provider"] is None and trace["model"] is None
    settings.assert_not_called()
    case["factory"].assert_not_called()
    case["model"].with_structured_output.assert_not_called()
    case["structured"].ainvoke.assert_not_called()
