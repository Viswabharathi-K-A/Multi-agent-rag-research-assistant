"""Offline Summary-worker tests with mocked retrieval and generation."""

import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app.agents import summary
from app.config import Settings


@pytest.fixture
def case(monkeypatch):
    chunk = Document(page_content="Leader election evidence", metadata={
        "chunk_id": "raft.pdf:p6:c1", "source": "raft.pdf", "title": "raft", "page": 6,
        "document_id": "document:raft.pdf", "source_kind": "document", "start_index": 0,
    })
    documents = Mock(return_value=[chunk])
    llm = Mock(ainvoke=AsyncMock(return_value=AIMessage(content="Summary [raft.pdf:p6:c1]")))
    factory = Mock(return_value=llm)
    settings = Settings(_env_file=None, research_timeout_seconds=2)
    monkeypatch.setattr(summary, "retrieve_documents", documents)
    monkeypatch.setattr(summary, "get_agent_llm", factory)
    monkeypatch.setattr(summary, "get_agent_provider_info", lambda role: ("google", "mock-model"))
    monkeypatch.setattr(summary, "get_settings", lambda: settings)
    return {"state": {"user_query": "Summarize Raft", "current_task": {
        "agent": "summary", "instruction": "Summarize election evidence"}},
        "chunk": chunk, "documents": documents, "llm": llm,
        "factory": factory, "settings": settings}


@pytest.mark.asyncio
async def test_direct_document_summary_retrieves_and_preserves_citations(case):
    output = await summary.summary_node(case["state"])
    result = output["results"][0]
    assert result["success"]
    assert "[raft.pdf:p6:c1] raft - raft.pdf, PDF page 6" in result["content"]
    assert result["sources"][0]["metadata"] == case["chunk"].metadata
    assert result["sources"][0]["content"] == case["chunk"].page_content
    case["documents"].assert_called_once_with("Summarize election evidence", case["settings"])
    case["factory"].assert_called_once_with("summary")
    messages = case["llm"].ainvoke.call_args.args[0]
    context = json.loads(messages[1].content)
    assert context["sources"] == result["sources"]
    assert context["original_query"] == "Summarize Raft"
    assert len(output["results"]) == 1
    assert any(event["tool"] == "chroma_retrieval" for event in output["trace"])


@pytest.mark.asyncio
async def test_existing_findings_skip_retrieval_and_preserve_web_sources(case):
    source = {"source_id": "web-1", "source_kind": "web", "title": "Guide",
              "url": "https://example.com/guide", "content": "Evidence", "metadata": {}}
    earlier = {"agent": "research", "success": True, "content": "Finding https://example.com/guide",
               "sources": [source]}
    failed = {"agent": "code", "success": False, "content": "Do not summarize this as success"}
    case["state"]["results"] = [earlier, earlier, failed]
    case["llm"].ainvoke.return_value = AIMessage(content="Concise finding https://example.com/guide")
    result = (await summary.summary_node(case["state"]))["results"][0]
    assert result["success"]
    assert result["sources"] == [source]
    assert "[web-1] Guide - https://example.com/guide" in result["content"]
    case["documents"].assert_not_called()
    context = json.loads(case["llm"].ainvoke.call_args.args[0][1].content)
    assert failed not in context["completed_results"]
    assert case["state"]["results"] == [earlier, earlier, failed]


@pytest.mark.asyncio
async def test_can_summarize_code_findings_without_external_sources(case):
    case["state"]["results"] = [{"agent": "code", "success": True,
                                  "content": "Proposed code, not executed", "sources": []}]
    case["llm"].ainvoke.return_value = AIMessage(content="The proposed code was not executed.")
    result = (await summary.summary_node(case["state"]))["results"][0]
    assert result["success"] and result["sources"] == []
    case["documents"].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["No citations here", "  "], ids=["missing_citations", "blank"])
async def test_missing_citations_or_blank_response_fails_and_keeps_evidence(case, response):
    case["llm"].ainvoke.return_value = AIMessage(content=response)
    result = (await summary.summary_node(case["state"]))["results"][0]
    assert not result["success"] and not result["content"]
    assert result["sources"][0]["metadata"]["page"] == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", [
    "raft.pdf:p99:c1",
    "raft.pdf:p6:c1-c2",
    "raft.pdf:p6:c1, raft.pdf:p6:c2",
], ids=["fabricated", "range", "combined"])
async def test_invalid_document_citation_fails_even_with_valid_reference(case, reference):
    case["llm"].ainvoke.return_value = AIMessage(
        content=f"Supported [raft.pdf:p6:c1]. Invalid [{reference}]"
    )

    output = await summary.summary_node(case["state"])
    result = output["results"][0]

    assert not result["success"]
    assert result["content"] == ""
    assert "exact supplied IDs" in result["error"]
    assert result["sources"][0]["source_id"] == "raft.pdf:p6:c1"
    assert result["sources"][0]["content"] == case["chunk"].page_content
    assert output["trace"][-1]["action"] == "summary_failed"
    assert not any(event["action"] == "summary_completed" for event in output["trace"])
    case["llm"].ainvoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("task", [None, {"agent": "code", "instruction": "Code"},
                                      {"agent": "summary", "instruction": " "}])
async def test_invalid_task_skips_retrieval_and_model(case, task):
    case["state"]["current_task"] = task
    result = (await summary.summary_node(case["state"]))["results"][0]
    assert not result["success"]
    case["documents"].assert_not_called()
    case["factory"].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["empty", "exception"])
async def test_retrieval_failure_skips_generation(case, failure):
    if failure == "empty":
        case["documents"].return_value = []
    else:
        case["documents"].side_effect = ValueError("private database detail")
    result = (await summary.summary_node(case["state"]))["results"][0]
    assert not result["success"] and "private" not in result["error"]
    case["factory"].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "timeout", "cancel"])
async def test_model_failure_preserves_sources_and_cancellation_propagates(case, failure):
    if failure == "exception":
        case["llm"].ainvoke.side_effect = ValueError("private provider details")
    elif failure == "cancel":
        case["llm"].ainvoke.side_effect = asyncio.CancelledError()
    else:
        async def stall(messages):
            await asyncio.Event().wait()
        case["llm"].ainvoke.side_effect = stall
        case["settings"].research_timeout_seconds = 0.02
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await summary.summary_node(case["state"])
    else:
        result = (await summary.summary_node(case["state"]))["results"][0]
        assert not result["success"] and "private" not in result["error"]
        assert result["sources"]
