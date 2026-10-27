"""Exercise the real MCP client with SDK result models and mocked transport."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from copy import deepcopy
from unittest.mock import AsyncMock, Mock, call
from urllib.parse import parse_qs, urlsplit

import pytest
from mcp import types

from app.config import Settings
from app.services import tavily_mcp as mcp


@pytest.fixture
def case(monkeypatch):
    settings = Settings(_env_file=None, tavily_api_key="fake key+&?", tavily_max_results=2,
                        tavily_timeout_seconds=2)
    tool = types.Tool(name="tavily_search", input_schema={
        "type": "object", "properties": {
            "query": {"type": "string"}, "search_depth": {"type": "string"},
            "max_results": {"type": "integer"},
        }, "required": ["query"],
    })
    result = types.CallToolResult(content=[], structured_content={"results": [{
        "url": "https://example.com/reference?version=1&section=2",
        "title": "Reference", "content": "Evidence", "score": 0.9,
    }]})
    session = Mock()
    session.initialize = AsyncMock()
    session.list_tools = AsyncMock(return_value=types.ListToolsResult(tools=[tool]))
    session.call_tool = AsyncMock(return_value=result)
    events = []
    read, write = object(), object()

    @asynccontextmanager
    async def transport(url):
        events.append("transport_enter")
        try:
            yield read, write
        finally:
            events.append("transport_exit")

    @asynccontextmanager
    async def connection(*args):
        events.append("session_enter")
        try:
            yield session
        finally:
            events.append("session_exit")

    transport_factory = Mock(side_effect=transport)
    session_factory = Mock(side_effect=connection)
    monkeypatch.setattr(mcp, "streamable_http_client", transport_factory)
    monkeypatch.setattr(mcp, "ClientSession", session_factory)
    monkeypatch.setattr(mcp, "get_settings", lambda: settings)
    return {"settings": settings, "tool": tool, "session": session, "events": events,
            "transport": transport_factory, "connection": session_factory,
            "read": read, "write": write}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["tavily_search", "tavily-search"])
async def test_search_lifecycle_authentication_arguments_and_evidence(case, name):
    case["tool"].name = name

    tool_name, sources = await mcp.search_web("Current research")

    assert tool_name == name
    url = urlsplit(case["transport"].call_args.args[0])
    assert (url.scheme, url.netloc, url.path) == ("https", "mcp.tavily.com", "/mcp/")
    assert parse_qs(url.query) == {"tavilyApiKey": [case["settings"].tavily_api_key]}
    case["connection"].assert_called_once_with(case["read"], case["write"])
    assert case["session"].mock_calls == [
        call.initialize(), call.list_tools(),
        call.call_tool(name, arguments={"query": "Current research", "search_depth": "basic",
                                        "max_results": 2}),
    ]
    assert case["events"] == ["transport_enter", "session_enter", "session_exit", "transport_exit"]
    assert sources == [{"source_id": "web-1", "title": "Reference",
                        "url": "https://example.com/reference?version=1&section=2",
                        "content": "Evidence", "metadata": {"score": 0.9}}]


@pytest.mark.asyncio
async def test_discovery_skips_incompatible_tools_and_omits_unadvertised_arguments(case):
    valid = types.Tool(name="tavily-search", input_schema={
        "properties": {"query": {"type": "string"}}, "required": ["query"],
    })
    case["session"].list_tools.return_value = types.ListToolsResult(tools=[
        types.Tool(name="other_tool", input_schema={"properties": {"query": {"type": "string"}}}),
        types.Tool(name="tavily_search", input_schema={"properties": {"query": {"type": "integer"}}}),
        valid,
    ])

    await mcp.search_web("Query", case["settings"])

    case["session"].call_tool.assert_awaited_once_with("tavily-search", arguments={"query": "Query"})


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_key", "blank_key", "blank_query"])
async def test_invalid_configuration_or_query_does_not_connect(case, failure):
    query = "Query"
    if failure == "missing_key":
        case["settings"].tavily_api_key = None
    elif failure == "blank_key":
        case["settings"].tavily_api_key = "  "
    else:
        query = " \n "

    with pytest.raises(mcp.RetrievalError, match="missing|empty"):
        await mcp.search_web(query, case["settings"])

    case["transport"].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["no_tool", "unsupported_required_argument"])
async def test_discovery_failure_does_not_invoke_tool_and_closes_contexts(case, failure):
    if failure == "no_tool":
        case["session"].list_tools.return_value = types.ListToolsResult(tools=[])
    else:
        case["tool"].input_schema["required"].append("unsupported")

    with pytest.raises(mcp.RetrievalError, match="not found|unsupported argument"):
        await mcp.search_web("Query", case["settings"])

    case["session"].call_tool.assert_not_awaited()
    assert case["events"][-2:] == ["session_exit", "transport_exit"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["initialize", "list_tools", "call_tool"])
async def test_session_errors_are_safe_and_cleanup_runs(case, stage):
    getattr(case["session"], stage).side_effect = RuntimeError(
        "private https://mcp.tavily.com/mcp/?tavilyApiKey=fake-secret")

    with pytest.raises(mcp.RetrievalError, match="^Tavily MCP request failed$") as error:
        await mcp.search_web("Query", case["settings"])

    assert error.value.__suppress_context__
    assert "fake-secret" not in str(error.value)
    assert case["events"][-2:] == ["session_exit", "transport_exit"]


@pytest.mark.asyncio
async def test_transport_connection_failure_is_safe(case):
    case["transport"].side_effect = RuntimeError("private connection details")

    with pytest.raises(mcp.RetrievalError, match="^Tavily MCP request failed$"):
        await mcp.search_web("Query", case["settings"])

    case["connection"].assert_not_called()


@pytest.mark.asyncio
async def test_tool_error_remains_safe_and_contexts_close(case):
    case["session"].call_tool.return_value = types.CallToolResult(
        is_error=True, content=[types.TextContent(type="text", text="private upstream details")])

    with pytest.raises(mcp.RetrievalError, match="^Tavily search failed$"):
        await mcp.search_web("Query", case["settings"])

    assert case["events"][-2:] == ["session_exit", "transport_exit"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["initialize", "list_tools", "call_tool"])
async def test_timeout_cancels_pending_work_and_closes_contexts(case, stage):
    cancelled = asyncio.Event()

    async def stall(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    case["settings"].tavily_timeout_seconds = 0.02
    getattr(case["session"], stage).side_effect = stall

    with pytest.raises(mcp.RetrievalError, match="^Tavily search timed out$"):
        await mcp.search_web("Query", case["settings"])

    assert cancelled.is_set()
    assert case["events"][-2:] == ["session_exit", "transport_exit"]


@pytest.mark.asyncio
async def test_caller_cancellation_propagates_and_closes_contexts(case):
    entered = asyncio.Event()

    async def stall(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    case["session"].call_tool.side_effect = stall
    task = asyncio.create_task(mcp.search_web("Query", case["settings"]))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert case["events"][-2:] == ["session_exit", "transport_exit"]


@pytest.mark.parametrize("format", ["structured", "json_text"])
def test_result_formats_preserve_urls_metadata_and_input(format):
    data = {"results": [{"url": "https://example.com/paper?q=a%20b&v=2#section",
                         "title": "Paper", "content": "Evidence", "score": 0.8,
                         "published_date": "2026-10-01", "author": "Author"}]}
    response = types.CallToolResult(content=[], structured_content=data)
    if format == "json_text":
        response.structured_content = None
        response.content = [types.ImageContent(type="image", data="AA==", mime_type="image/png"),
                            types.TextContent(type="text", text="Not JSON"),
                            types.TextContent(type="text", text='{"note":"not results"}'),
                            types.TextContent(type="text", text=json.dumps(data))]
    original = deepcopy(response)

    sources = mcp.extract_sources(response, 2)

    assert sources[0]["url"] == data["results"][0]["url"]
    assert sources[0]["metadata"] == {"score": 0.8, "published_date": "2026-10-01", "author": "Author"}
    assert response == original


def test_sources_skip_invalid_entries_deduplicate_and_apply_limits():
    response = types.CallToolResult(content=[], structured_content={"results": [
        None, {"url": "file:///private", "content": "Rejected"},
        {"url": "https://[invalid", "content": "Rejected"},
        {"url": "https://example.com/blank", "content": "  "},
        {"url": "https://example.com/wrong", "title": 3, "content": "Rejected"},
        {"url": "https://example.com/one", "title": "T" * 501, "content": "C" * 6001},
        {"url": "https://example.com/one", "content": "Duplicate"},
        {"url": "https://example.com/two", "snippet": "Fallback snippet"},
        {"url": "https://example.com/three", "content": "Beyond limit"},
    ]})

    sources = mcp.extract_sources(response, 2)

    assert [source["source_id"] for source in sources] == ["web-1", "web-2"]
    assert [source["url"] for source in sources] == ["https://example.com/one", "https://example.com/two"]
    assert sources[0]["title"] == "T" * 500
    assert sources[0]["content"] == "C" * 6000
    assert sources[1]["content"] == "Fallback snippet"


@pytest.mark.parametrize("data", [None, [], {}, {"results": "wrong"}])
def test_invalid_result_shapes_are_rejected(data):
    response = types.CallToolResult(content=[], structured_content=data)

    with pytest.raises(mcp.RetrievalError, match="Invalid Tavily search results"):
        mcp.extract_sources(response, 2)


def test_empty_results_are_distinct_from_unusable_results():
    assert mcp.extract_sources(types.CallToolResult(content=[], structured_content={"results": []}), 2) == []
    response = types.CallToolResult(content=[], structured_content={"results": [{"url": "javascript:bad"}]})
    with pytest.raises(mcp.RetrievalError, match="no usable sources"):
        mcp.extract_sources(response, 2)


@pytest.mark.parametrize("location", ["message", "exception", "formatted_exception"])
@pytest.mark.parametrize("marker", ["https://mcp.tavily.com/mcp/?key=fake", "TAVILYAPIKEY=fake"])
def test_sensitive_log_records_are_suppressed(location, marker):
    record = logging.LogRecord("httpx2", logging.ERROR, __file__, 1, "Request failed", (), None)
    if location == "message":
        record.msg = "Request %s"
        record.args = (marker,)
    elif location == "exception":
        error = RuntimeError(marker)
        record.exc_info = (RuntimeError, error, None)
    else:
        record.exc_text = "Traceback: " + marker

    assert not mcp.redact_log(record)


def test_unrelated_log_records_remain_and_filters_are_attached():
    record = logging.LogRecord("httpx2", logging.INFO, __file__, 1, "Connection closed", (), None)
    assert mcp.redact_log(record)
    for name in ("httpx2", "mcp.client.streamable_http"):
        assert mcp.redact_log in logging.getLogger(name).filters
