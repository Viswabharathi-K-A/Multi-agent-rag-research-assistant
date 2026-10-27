"""Research and Code reach the same real MCP client with mocked external I/O."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, call

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from mcp import types

from app.agents import code, research
from app.config import Settings
from app.services import tavily_mcp as mcp


@pytest.mark.asyncio
async def test_research_and_code_invoke_same_discovered_mcp_tool(monkeypatch):
    settings = Settings(_env_file=None, tavily_api_key="fake-key", tavily_max_results=1,
                        tavily_timeout_seconds=2, research_timeout_seconds=5)
    tool = types.Tool(name="tavily-search", input_schema={
        "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
        "required": ["query"],
    })
    queries = ["Find current Python release information", "Find Python asyncio API references"]
    urls = ["https://example.com/python-release", "https://example.com/asyncio"]
    sessions = []
    lifecycle = []

    @asynccontextmanager
    async def transport(url):
        index = len(sessions)
        lifecycle.append((index, "transport_enter"))
        try:
            yield object(), object()
        finally:
            lifecycle.append((index, "transport_exit"))

    @asynccontextmanager
    async def connection(read, write):
        index = len(sessions)
        session = Mock()
        session.initialize = AsyncMock()
        session.list_tools = AsyncMock(return_value=types.ListToolsResult(tools=[tool]))
        session.call_tool = AsyncMock(return_value=types.CallToolResult(
            content=[], structured_content={"results": [{
                "url": urls[index], "title": "Technical reference",
                "content": f"Evidence for task {index + 1}",
            }]}))
        sessions.append(session)
        lifecycle.append((index, "session_enter"))
        try:
            yield session
        finally:
            lifecycle.append((index, "session_exit"))

    monkeypatch.setattr(mcp, "streamable_http_client", transport)
    monkeypatch.setattr(mcp, "ClientSession", connection)
    monkeypatch.setattr(mcp, "get_settings", lambda: settings)
    assert research.search_web is mcp.search_web
    assert code.search_web is mcp.search_web
    documents = Mock(side_effect=AssertionError("Web-only research must not retrieve documents"))
    monkeypatch.setattr(research, "retrieve_documents", documents)
    for module in (research, code):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(research, "get_agent_provider_info", lambda role: ("google", "mock-research"))
    monkeypatch.setattr(code, "get_agent_provider_info", lambda role: ("openai", "mock-code"))

    research_model = Mock(ainvoke=AsyncMock(return_value=AIMessage(content=f"Release findings {urls[0]}")))
    code_model = Mock(ainvoke=AsyncMock(side_effect=[
        AIMessage(content="", tool_calls=[{
            "name": "search_technical_web", "args": {"query": queries[1]}, "id": "technical-search",
        }]),
        AIMessage(content=f"Proposed asyncio example based on {urls[1]}"),
    ]))
    code_model.bind_tools.return_value = code_model
    monkeypatch.setattr(research, "get_agent_llm", lambda role: research_model)
    monkeypatch.setattr(code, "get_agent_llm", lambda role: code_model)

    research_output = await research.research_node({
        "user_query": "Use web research to explain current Python changes and an asyncio example",
        "current_task": {"agent": "research", "instruction": queries[0], "retrieval_mode": "web"},
    })
    research_result = research_output["results"][0]
    code_output = await code.code_node({
        "user_query": "Use web research to explain current Python changes and an asyncio example",
        "current_task": {"agent": "code", "instruction": "Check asyncio references and propose an example"},
        "results": [research_result],
    })
    code_result = code_output["results"][0]

    assert research_result["success"] and code_result["success"]
    assert len(sessions) == 2
    for index, session in enumerate(sessions):
        assert session.mock_calls == [
            call.initialize(), call.list_tools(),
            call.call_tool("tavily-search", arguments={"query": queries[index], "max_results": 1}),
        ]
        assert [action for owner, action in lifecycle if owner == index] == [
            "transport_enter", "session_enter", "session_exit", "transport_exit",
        ]
    assert [source["url"] for source in research_result["sources"]] == [urls[0]]
    assert [source["url"] for source in code_result["sources"]] == urls
    assert all(source["source_kind"] == "web" for source in code_result["sources"])
    for output, agent in ((research_output, "research"), (code_output, "code")):
        events = [event for event in output["trace"] if event["action"] == "retrieval_completed"]
        assert len(events) == 1 and events[0]["node"] == agent
        assert events[0]["tool"] == "tavily-search"
    research_context = json.loads(research_model.ainvoke.call_args.args[0].to_messages()[1].content)
    assert research_context["sources"] == research_result["sources"]
    code_messages = code_model.ainvoke.call_args.args[0]
    tool_message = next(message for message in code_messages if isinstance(message, ToolMessage))
    assert tool_message.tool_call_id == "technical-search"
    assert json.loads(tool_message.content)["sources"][0]["url"] == urls[1]
    assert urls[0] in research_result["content"] and urls[1] in code_result["content"]
    research_model.ainvoke.assert_awaited_once()
    assert code_model.ainvoke.await_count == 2
    documents.assert_not_called()
