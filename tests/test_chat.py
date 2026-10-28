"""Offline chat/SSE contracts, including the real graph with a streaming fake model."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.runnables import RunnableLambda

from app import llm, main
from app.agents import research, supervisor
from app.config import Settings
from app.schemas import ChatRequest


def parse_events(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = []
    for frame in response.text.replace("\r\n", "\n").split("\n\n"):
        lines = frame.splitlines()
        data = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if data is not None:
            event = json.loads(data)
            assert f"event: {event['type']}" in lines
            events.append(event)
    return events


@pytest.fixture
def scripted(monkeypatch):
    items = []

    async def stream(*args, **kwargs):
        for item in items:
            if isinstance(item, Exception):
                raise item
            yield item

    factory = Mock(return_value=SimpleNamespace(astream=stream))
    monkeypatch.setattr(main, "build_agent_graph", factory)
    return items, factory


@pytest.mark.parametrize("body", [{}, {"query": ""}, {"query": " \t\n"},
                                  {"query": "x" * 12001}, {"query": None}, {"query": 123}])
def test_invalid_request_never_starts_graph(scripted, body):
    with TestClient(main.app) as client:
        assert client.post("/chat", json=body).status_code == 422
    scripted[1].assert_not_called()


def test_real_graph_streams_worker_generation_and_final_answer(monkeypatch):
    settings = Settings(_env_file=None, research_timeout_seconds=5,
                        supervisor_provider="openai", supervisor_model="fake-supervisor")
    chunk = Document(page_content="Election evidence", metadata={
        "chunk_id": "raft.pdf:p6:c1", "source": "raft.pdf", "title": "raft", "page": 6})
    contexts = []

    def decide(messages):
        context = json.loads(messages[1].content)
        contexts.append(context)
        results = context["completed_results"]
        return supervisor.SupervisorDecision(
            next_agent="finish" if results else "research", instruction="Find election evidence",
            reason="Use corpus evidence", final_answer=results[-1]["content"] if results else "")

    model = Mock()
    model.with_structured_output.return_value = RunnableLambda(decide)
    monkeypatch.setattr(llm, "get_agent_llm", Mock(return_value=model))
    monkeypatch.setattr(supervisor, "get_settings", lambda: settings)
    monkeypatch.setattr(research, "get_settings", lambda: settings)
    monkeypatch.setattr(research, "get_agent_provider_info", lambda role: ("google", "fake-research"))
    monkeypatch.setattr(research, "get_agent_llm", lambda role: FakeListChatModel(
        responses=["Evidence [raft.pdf:p6:c1]"]))
    documents = Mock(return_value=[chunk])
    web = AsyncMock(side_effect=AssertionError("Unexpected web request"))
    monkeypatch.setattr(research, "retrieve_documents", documents)
    monkeypatch.setattr(research, "search_web", web)

    with TestClient(main.app) as client:
        events = parse_events(client.post("/chat", json={"query": " Explain Raft "}))

    assert events[0] == {"type": "start", "data": {"query": "Explain Raft"}}
    tokens = [event["data"] for event in events if event["type"] == "token"]
    assert len(tokens) > 1
    assert "".join(token["text"] for token in tokens) == "Evidence [raft.pdf:p6:c1]"
    assert all(token["agent"] == "research" for token in tokens)
    assert len(contexts) == 2 and contexts[1]["completed_results"][0]["success"]
    assert events[-1]["type"] == "done"
    assert events[-1]["data"]["final_answer"] == contexts[1]["completed_results"][0]["content"]
    routing = [event["data"] for event in events if event["type"] == "routing"]
    assert [event["agent"] for event in routing] == ["supervisor", "research", "supervisor"]
    assert {event["provider"] for event in routing} == {"openai", "google"}
    assert all(event["model"] and event["reason"] for event in routing)
    citations = [event["data"] for event in events if event["type"] == "citation"]
    assert len(citations) == 1
    assert citations[0]["page"] == 6 and citations[0]["excerpt"] == "Election evidence"
    traces = [event["data"] for event in events if event["type"] == "trace"]
    assert sum(trace["event"] == "delegate" for trace in traces) == 1
    assert sum(trace["event"] == "finish" for trace in traces) == 1
    documents.assert_called_once()
    web.assert_not_awaited()


def test_control_tool_and_reasoning_content_are_not_answer_tokens(scripted):
    items, _ = scripted
    for message, agent in [
        (AIMessageChunk(content="PRIVATE CONTROL"), "supervisor"),
        (ToolMessage(content="PRIVATE TOOL", tool_call_id="tool-1"), "code"),
        (AIMessage(content="Completed response"), "research"),
        (AIMessageChunk(content="PRIVATE UNKNOWN"), "unknown"),
        (AIMessageChunk(content="", tool_call_chunks=[{
            "name": "inspect_python", "args": "PRIVATE ARGS", "id": "tool-1", "index": 0}]), "code"),
        (AIMessageChunk(content=[{"type": "text", "text": "Visible\ntext"},
                                 {"type": "reasoning", "reasoning": "PRIVATE REASONING"}]), "summary"),
    ]:
        items.append(("messages", (message, {"langgraph_node": agent})))
    items.append(("updates", {"supervisor": {"next_agent": "finish", "final_answer": "Final"}}))
    with TestClient(main.app) as client:
        response = client.post("/chat", json={"query": "Explain"})
        events = parse_events(response)
    assert "PRIVATE" not in response.text
    assert [event["data"] for event in events if event["type"] == "token"] == [
        {"agent": "summary", "text": "Visible\ntext"}]


def test_citations_deduplicate_by_location_and_id_per_request(scripted):
    items, _ = scripted
    sources = [{"source_id": "web-1", "source_kind": "web", "url": url,
                "content": "Web evidence"} for url in ("https://example.com/a", "https://example.com/b")]
    items.extend([
        ("updates", {"research": {"results": [{"sources": sources}]}}),
        ("updates", {"summary": {"results": [{"sources": sources}]}}),
        ("updates", {"supervisor": {"next_agent": "finish", "final_answer": "Final"}}),
    ])
    with TestClient(main.app) as client:
        for _ in range(2):
            events = parse_events(client.post("/chat", json={"query": "Explain"}))
            citations = [event["data"] for event in events if event["type"] == "citation"]
            assert [citation["document"] for citation in citations] == [source["url"] for source in sources]
            assert all(citation["page"] is None for citation in citations)


def test_url_source_ids_survive_sse_and_repeated_worker_results(scripted):
    urls = ["https://example.com/ref?version=1&section=2#details", "https://other.example/ref"]
    sources = [{"source_id": url, "source_kind": "web", "url": url,
                "content": "Evidence"} for url in urls]
    answer = "First claim [" + urls[0] + "]. Second claim [" + urls[1] + "]."
    scripted[0].extend([
        ("updates", {"research": {"results": [{"sources": sources}]}}),
        ("updates", {"code": {"results": [{"sources": list(reversed(sources))}]}}),
        ("updates", {"supervisor": {"next_agent": "finish", "final_answer": answer}}),
    ])

    with TestClient(main.app) as client:
        events = parse_events(client.post("/chat", json={"query": "Compare these sources"}))

    citations = [event["data"] for event in events if event["type"] == "citation"]
    assert [source["source_id"] for source in citations] == urls
    assert [source["document"] for source in citations] == urls
    assert events[-1]["data"]["final_answer"] == answer


@pytest.mark.parametrize("failure_at_start", [False, True])
def test_unexpected_errors_are_safe_and_never_emit_done(scripted, failure_at_start):
    items, factory = scripted
    error = RuntimeError("PRIVATE provider credential")
    if failure_at_start:
        factory.side_effect = error
    else:
        items.extend([("messages", (AIMessageChunk(content="Partial"),
                                   {"langgraph_node": "code"})), error])
    with TestClient(main.app) as client:
        response = client.post("/chat", json={"query": "Explain"})
        events = parse_events(response)
    assert events[0]["type"] == "start" and events[-1]["type"] == "error"
    assert not any(event["type"] == "done" for event in events)
    assert "PRIVATE" not in response.text
    assert events[-1]["data"]["message"]


@pytest.mark.parametrize("updates", [{}, {"supervisor": {"next_agent": "finish", "final_answer": ""}}])
def test_missing_final_answer_reports_error(scripted, updates):
    scripted[0].append(("updates", updates))
    with TestClient(main.app) as client:
        events = parse_events(client.post("/chat", json={"query": "Explain"}))
    assert events[-1]["type"] == "error"
    assert not any(event["type"] == "done" for event in events)


@pytest.mark.asyncio
async def test_token_is_yielded_before_graph_completion(monkeypatch):
    completed = asyncio.Event()

    async def stream(*args, **kwargs):
        yield "messages", (AIMessageChunk(content="First fragment"), {"langgraph_node": "research"})
        await completed.wait()
        yield "updates", {"supervisor": {"next_agent": "finish", "final_answer": "Final"}}

    monkeypatch.setattr(main, "build_agent_graph", lambda: SimpleNamespace(astream=stream))
    response = await main.chat(ChatRequest(query="Explain"))
    iterator = response.body_iterator
    try:
        assert json.loads((await anext(iterator))["data"])["type"] == "start"
        token = await asyncio.wait_for(anext(iterator), timeout=1)
        assert json.loads(token["data"]) == {
            "type": "token", "data": {"agent": "research", "text": "First fragment"}}
        assert not completed.is_set()
        completed.set()
        assert json.loads((await anext(iterator))["data"])["type"] == "done"
    finally:
        await iterator.aclose()
