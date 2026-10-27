"""Offline Code-worker tests using real tool dispatch and mocked LLM/MCP calls."""

import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.agents import code
from app.config import Settings


@pytest.fixture
def case(monkeypatch):
    llm = Mock(ainvoke=AsyncMock(return_value=AIMessage(content="Proposed implementation")))
    factory = Mock(return_value=Mock(bind_tools=Mock(return_value=llm)))
    web = AsyncMock(return_value=("tavily_search", [{
        "source_id": "web-1", "title": "Python reference", "url": "https://example.com/python",
        "content": "Technical evidence", "metadata": {},
    }]))
    settings = Settings(_env_file=None, research_timeout_seconds=2)
    monkeypatch.setattr(code, "get_agent_llm", factory)
    monkeypatch.setattr(code, "get_agent_provider_info", lambda role: ("openai", "mock-model"))
    monkeypatch.setattr(code, "get_settings", lambda: settings)
    monkeypatch.setattr(code, "search_web", web)
    return {"state": {"user_query": "Explain this code", "current_task": {
        "agent": "code", "instruction": "Inspect Python"}},
        "llm": llm, "factory": factory, "web": web, "settings": settings}


def test_python_inspection_does_not_execute_source(tmp_path):
    marker = tmp_path / "must-not-exist"
    source = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\nclass Cache:\n    async def get(self):\n        return 1\n"
    result = code.inspect_python.invoke({"source": source})
    assert result["valid_syntax"]
    assert result["imports"] == ["pathlib"]
    assert result["classes"] == [{"name": "Cache", "line": 3}]
    assert result["functions"] == [{"name": "get", "line": 4}]
    assert not marker.exists()


@pytest.mark.parametrize("source", ["def broken(:", "x" * 50_001], ids=["syntax_error", "oversized"])
def test_python_inspection_rejects_invalid_or_oversized_source(source):
    result = code.inspect_python.invoke({"source": source})
    assert not result["valid_syntax"]
    assert result["error"]


@pytest.mark.asyncio
async def test_self_contained_task_uses_no_web_and_returns_only_deltas(case):
    earlier = {"agent": "research", "success": True, "content": "Evidence",
               "sources": [{"source_id": "raft.pdf:p6:c1", "content": "Paper evidence"}]}
    case["state"]["results"] = [earlier]
    output = await code.code_node(case["state"])
    result = output["results"][0]
    assert result["success"] and result["content"] == "Proposed implementation"
    assert result["sources"] == earlier["sources"]
    assert len(output["results"]) == 1
    case["web"].assert_not_called()
    case["factory"].assert_called_once_with("code")
    prompt = case["llm"].ainvoke.call_args.args[0]
    assert json.loads(prompt[1].content)["completed_results"] == [earlier]
    assert all(event["provider"] == "openai" for event in output["trace"])


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args", [
    ("inspect_python", {"source": "def add(a, b):\n    return a + b"}),
    ("search_technical_web", {"query": "Python reference"}),
    ("unknown_tool", {}),
])
async def test_model_selected_tools_reach_followup_prompt(case, name, args):
    seen = []

    async def respond(messages):
        seen.append(list(messages))
        if len(seen) == 1:
            return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call-1"}])
        return AIMessage(content="Analysis with https://example.com/python")

    case["llm"].ainvoke.side_effect = respond
    output = await code.code_node(case["state"])
    assert output["results"][0]["success"]
    tool_message = seen[1][-1]
    assert isinstance(tool_message, ToolMessage) and tool_message.tool_call_id == "call-1"
    payload = json.loads(tool_message.content)
    if name == "inspect_python":
        assert payload["valid_syntax"]
        assert payload["functions"][0]["name"] == "add"
        case["web"].assert_not_called()
    elif name == "search_technical_web":
        case["web"].assert_awaited_once_with("Python reference")
        assert payload["sources"][0]["source_kind"] == "web"
        assert output["results"][0]["sources"] == payload["sources"]
        assert any(event["tool"] == "tavily_search" for event in output["trace"])
    else:
        assert payload == {"error": "Unknown code tool"}
        case["web"].assert_not_called()


@pytest.mark.asyncio
async def test_tool_failure_is_visible_to_model_without_private_details(case):
    case["web"].side_effect = RuntimeError("private upstream details")
    first = AIMessage(content="", tool_calls=[{
        "name": "search_technical_web", "args": {"query": "Python"}, "id": "call-1"}])
    case["llm"].ainvoke.side_effect = [first, AIMessage(content="External lookup failed")]
    output = await code.code_node(case["state"])
    assert output["results"][0]["success"]
    messages = case["llm"].ainvoke.call_args.args[0]
    tool_message = next(message for message in messages if isinstance(message, ToolMessage))
    assert json.loads(tool_message.content) == {"error": "Code tool failed"}
    assert any(event["action"] == "tool_failed" for event in output["trace"])


@pytest.mark.asyncio
async def test_repeated_tool_requests_stop_at_limit(case):
    case["llm"].ainvoke.return_value = AIMessage(content="", tool_calls=[{
        "name": "inspect_python", "args": {"source": "x = 1"}, "id": "call-1"}])
    result = (await code.code_node(case["state"]))["results"][0]
    assert not result["success"] and "limit" in result["error"]
    assert case["llm"].ainvoke.await_count == 10


@pytest.mark.asyncio
async def test_excessive_parallel_tool_requests_are_not_executed(case):
    case["llm"].ainvoke.return_value = AIMessage(content="", tool_calls=[
        {"name": "search_technical_web", "args": {"query": "Python"}, "id": f"call-{i}"}
        for i in range(11)
    ])
    result = (await code.code_node(case["state"]))["results"][0]
    assert not result["success"] and "limit" in result["error"]
    case["web"].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("task", [None, {"agent": "research", "instruction": "Research"},
                                      {"agent": "code", "instruction": " "}])
async def test_invalid_task_skips_model(case, task):
    case["state"]["current_task"] = task
    result = (await code.code_node(case["state"]))["results"][0]
    assert not result["success"]
    case["factory"].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["blank", "exception", "timeout", "cancel"])
async def test_generation_failures_and_cancellation(case, failure):
    if failure == "blank":
        case["llm"].ainvoke.return_value = AIMessage(content=" ")
    elif failure == "exception":
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
            await code.code_node(case["state"])
    else:
        result = (await code.code_node(case["state"]))["results"][0]
        assert not result["success"] and not result["content"]
        assert "private" not in result["error"]
