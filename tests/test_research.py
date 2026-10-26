"""Exercise the real Research LCEL chain with mocked retrieval and generation."""

import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from app.agents import research
from app.agents.state import ResearchState
from app.config import Settings
from app.services.tavily_mcp import RetrievalError


@pytest.fixture
def research_case(monkeypatch):
    chunk = Document(page_content="Corpus evidence {with braces}", metadata={
        "chunk_id": "raft.pdf:p7:c1", "document_id": "document:raft.pdf", "source": "raft.pdf",
        "title": "raft", "page": 7, "start_index": 0, "source_kind": "document",
    })
    web_source = {
        "source_id": "web-1", "title": "Web guide",
        "url": "https://example.com/guide", "content": "Current web evidence",
        "metadata": {"published_date": "2026-10-01"},
    }
    prompts = []

    async def respond(prompt):
        context = json.loads(prompt.to_messages()[1].content)
        prompts.append(context)
        citations = []
        for source in context["sources"]:
            citations.append(source.get("url", f"[{source['source_id']}]"))
        return AIMessage(content="Supported finding " + " ".join(citations))

    documents = Mock(return_value=[chunk])
    web = AsyncMock(return_value=("tavily_search", [web_source]))
    model = Mock(ainvoke=AsyncMock(side_effect=respond))
    factory = Mock(return_value=model)
    settings = Settings(_env_file=None, research_timeout_seconds=2)
    monkeypatch.setattr(research, "retrieve_documents", documents)
    monkeypatch.setattr(research, "search_web", web)
    monkeypatch.setattr(research, "get_agent_llm", factory)
    monkeypatch.setattr(research, "get_settings", lambda: settings)
    monkeypatch.setattr(research, "get_agent_provider_info", lambda role: ("google", "mock-model"))
    return {
        "state": {
            "user_query": "Original question",
            "current_task": {
                "agent": "research", "instruction": "Find evidence", "retrieval_mode": "documents",
            },
        },
        "chunk": chunk, "web_source": web_source, "documents": documents, "web": web,
        "model": model, "factory": factory, "prompts": prompts, "settings": settings,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["documents", "web", "both"])
async def test_selected_channels_and_evidence_reach_model(research_case, mode):
    case = research_case
    case["state"]["current_task"]["retrieval_mode"] = mode
    output = await research.research_node(case["state"])
    result = output["results"][0]
    assert result["success"]
    context = case["prompts"][0]
    assert context["original_query"] == "Original question"
    assert context["research_instruction"] == "Find evidence"
    assert context["retrieval_mode"] == mode
    assert context["sources"] == result["sources"]
    tools = {event["tool"] for event in output["trace"]}
    if mode in ("documents", "both"):
        case["documents"].assert_called_once_with("Find evidence", case["settings"])
        source = next(s for s in result["sources"] if s["source_kind"] == "document")
        assert source["content"] == case["chunk"].page_content
        assert source["metadata"] == case["chunk"].metadata
        assert source["metadata"] is not case["chunk"].metadata
        assert source["title"] == "raft"
        assert source["metadata"]["page"] == 7
        assert "[raft.pdf:p7:c1] raft - raft.pdf, PDF page 7" in result["content"]
        assert "Supported finding [raft.pdf:p7:c1]" in result["content"]
        assert "chroma_retrieval" in tools
    else:
        case["documents"].assert_not_called()
    if mode in ("web", "both"):
        case["web"].assert_awaited_once_with("Find evidence")
        source = next(s for s in result["sources"] if s["source_kind"] == "web")
        assert source == {**case["web_source"], "source_kind": "web"}
        assert case["web_source"]["url"] in result["content"]
        assert "[web-1] Web guide - https://example.com/guide" in result["content"]
        assert "source_kind" not in case["web_source"]
        assert "tavily_search" in tools
    else:
        case["web"].assert_not_awaited()
    case["factory"].assert_called_once_with("research")
    case["model"].ainvoke.assert_awaited_once()
    assert all(event["provider"] == "google" for event in output["trace"])
    assert all(event["model"] == "mock-model" for event in output["trace"])


@pytest.mark.asyncio
async def test_missing_page_does_not_add_a_page_reference(research_case):
    del research_case["chunk"].metadata["page"]
    result = (await research.research_node(research_case["state"]))["results"][0]
    assert result["success"]
    assert "[raft.pdf:p7:c1] raft - raft.pdf" in result["content"]
    assert "PDF page" not in result["content"]
    assert "page" not in research_case["prompts"][0]["sources"][0]["metadata"]


@pytest.mark.asyncio
async def test_chunks_from_same_paper_keep_distinct_page_references(research_case):
    second_chunk = Document(page_content="Evidence from the next page", metadata={
        **research_case["chunk"].metadata, "page": 8, "chunk_id": "raft.pdf:p8:c1",
    })
    research_case["documents"].return_value.append(second_chunk)
    result = (await research.research_node(research_case["state"]))["results"][0]
    assert result["success"]
    assert "[raft.pdf:p7:c1] raft - raft.pdf, PDF page 7" in result["content"]
    assert "[raft.pdf:p8:c1] raft - raft.pdf, PDF page 8" in result["content"]
    sources = research_case["prompts"][0]["sources"]
    assert [source["metadata"]["page"] for source in sources] == [7, 8]
    assert [source["source_id"] for source in sources] == ["raft.pdf:p7:c1", "raft.pdf:p8:c1"]


@pytest.mark.asyncio
async def test_omitted_mode_defaults_to_documents(research_case):
    del research_case["state"]["current_task"]["retrieval_mode"]
    result = (await research.research_node(research_case["state"]))["results"][0]
    assert result["success"]
    assert research_case["prompts"][0]["retrieval_mode"] == "documents"
    research_case["web"].assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("task", [
    None,
    {"agent": "code", "instruction": "Find evidence"},
    {"agent": "research", "instruction": "  "},
    {"agent": "research", "instruction": "Find evidence", "retrieval_mode": "invalid"},
])
async def test_invalid_tasks_do_not_retrieve_or_generate(research_case, task):
    research_case["state"]["current_task"] = task
    output = await research.research_node(research_case["state"])
    assert not output["results"][0]["success"]
    assert output["trace"][-1]["action"] == "research_failed"
    research_case["documents"].assert_not_called()
    research_case["web"].assert_not_awaited()
    research_case["factory"].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["documents", "web", "both"])
async def test_no_evidence_skips_model(research_case, mode):
    research_case["state"]["current_task"]["retrieval_mode"] = mode
    research_case["documents"].return_value = []
    research_case["web"].return_value = ("tavily_search", [])
    result = (await research.research_node(research_case["state"]))["results"][0]
    assert not result["success"]
    assert result["sources"] == []
    research_case["factory"].assert_not_called()


@pytest.mark.asyncio
async def test_empty_document_results_can_combine_with_web_evidence(research_case):
    research_case["state"]["current_task"]["retrieval_mode"] = "both"
    research_case["documents"].return_value = []
    result = (await research.research_node(research_case["state"]))["results"][0]
    assert result["success"]
    assert [source["source_kind"] for source in result["sources"]] == ["web"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["documents", "both"])
async def test_document_failure_does_not_fall_back_to_web(research_case, mode):
    research_case["state"]["current_task"]["retrieval_mode"] = mode
    research_case["documents"].side_effect = RuntimeError("private upstream details")
    result = (await research.research_node(research_case["state"]))["results"][0]
    assert not result["success"]
    assert "Document retrieval failed" in result["error"]
    assert "private" not in result["error"]
    research_case["web"].assert_not_awaited()
    research_case["factory"].assert_not_called()


@pytest.mark.asyncio
async def test_web_failure_preserves_collected_document_evidence(research_case):
    research_case["state"]["current_task"]["retrieval_mode"] = "both"
    research_case["web"].side_effect = RetrievalError("Tavily MCP request failed")
    result = (await research.research_node(research_case["state"]))["results"][0]
    assert not result["success"]
    assert result["sources"][0]["source_id"] == "raft.pdf:p7:c1"
    assert result["content"] == ""
    research_case["factory"].assert_not_called()


@pytest.mark.asyncio
async def test_model_failure_preserves_evidence_without_exposing_details(research_case):
    research_case["model"].ainvoke.side_effect = RuntimeError("private upstream details")
    result = (await research.research_node(research_case["state"]))["results"][0]
    assert not result["success"]
    assert result["sources"][0]["source_id"] == "raft.pdf:p7:c1"
    assert "private" not in result["error"]
    assert result["content"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    "Supported finding [raft.pdf:p7:c1]",
    [{"type": "text", "text": "Supported finding [raft.pdf:p7:c1]"}],
])
async def test_model_text_formats(research_case, response):
    research_case["model"].ainvoke.side_effect = None
    research_case["model"].ainvoke.return_value = AIMessage(content=response)
    result = (await research.research_node(research_case["state"]))["results"][0]
    assert result["success"]
    assert result["content"].startswith("Supported finding [raft.pdf:p7:c1]")


@pytest.mark.asyncio
async def test_blank_model_output_is_failure(research_case):
    research_case["model"].ainvoke.side_effect = None
    research_case["model"].ainvoke.return_value = AIMessage(content="  ")
    result = (await research.research_node(research_case["state"]))["results"][0]
    assert not result["success"]
    assert "no text" in result["error"]
    assert result["sources"]


@pytest.mark.asyncio
async def test_model_timeout_cancels_generation_and_preserves_evidence(research_case):
    cancelled = asyncio.Event()

    async def stalled_model(prompt):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    research_case["settings"].research_timeout_seconds = 0.05
    research_case["model"].ainvoke.side_effect = stalled_model
    result = (await research.research_node(research_case["state"]))["results"][0]
    assert not result["success"]
    assert "timed out" in result["error"]
    assert result["sources"]
    assert cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["web", "model"])
async def test_cancellation_propagates_to_caller(research_case, stage):
    if stage == "web":
        research_case["state"]["current_task"]["retrieval_mode"] = "web"
        research_case["web"].side_effect = asyncio.CancelledError()
    else:
        research_case["model"].ainvoke.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await research.research_node(research_case["state"])


@pytest.mark.asyncio
async def test_langgraph_appends_only_new_results_and_traces(research_case):
    previous_result = {
        "agent": "summary", "instruction": "Earlier task", "content": "Earlier result",
        "success": True, "error": None,
    }
    previous_trace = {
        "node": "supervisor", "action": "delegate", "detail": "Earlier trace",
        "provider": None, "model": None, "reason": "Research needed",
    }
    graph = StateGraph(ResearchState)
    graph.add_node("research", research.research_node)
    graph.add_edge(START, "research")
    graph.add_edge("research", END)
    output = await graph.compile().ainvoke({
        **research_case["state"], "results": [previous_result], "trace": [previous_trace],
    })
    assert len(output["results"]) == 2
    assert output["results"][0] == previous_result
    assert output["results"][1]["success"]
    assert output["trace"][0] == previous_trace
    assert output["trace"].count(previous_trace) == 1
    assert output["trace"][-1]["action"] == "research_completed"
