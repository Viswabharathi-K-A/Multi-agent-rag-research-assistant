"""Deterministic request measurements without external services."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.outputs import ChatGeneration, LLMResult

from app import llm, metrics
from app.config import Settings


def test_generation_usage_timing_and_private_content(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(metrics, "perf_counter", lambda: now[0])
    measurement = metrics.Measurements("request-one")
    measurement.on_chat_model_start({}, ["private prompt"], run_id="call",
                                    metadata={"agent": "research", "provider": "google"})
    now[0] = 2.0
    measurement.on_llm_new_token("private answer", run_id="call")
    now[0] = 3.0
    measurement.on_llm_new_token("more answer", run_id="call")
    now[0] = 5.0
    response = LLMResult(generations=[[ChatGeneration(message=AIMessage(
        content="private answer", usage_metadata={"input_tokens": 10,
                        "output_tokens": 4, "total_tokens": 14}))]])
    measurement.on_llm_end(response, run_id="call")
    snapshot = measurement.snapshot()
    assert snapshot["generation_seconds"] == 5
    assert snapshot["calls"][0]["first_token_seconds"] == 2
    assert snapshot["known_input_tokens"] == 10
    assert snapshot["known_output_tokens"] == 4
    assert snapshot["calls_with_unknown_usage"] == 0
    assert snapshot["unfinished_generation_calls"] == 0
    assert snapshot["server_ttft_seconds"] is None
    assert "private" not in json.dumps(snapshot)


def test_failed_and_unfinished_calls_do_not_invent_usage():
    measurement = metrics.Measurements("request-two")
    measurement.on_chat_model_start({}, [], run_id="failed")
    measurement.on_llm_error(ValueError("secret-api-key"), run_id="failed")
    measurement.on_chat_model_start({}, [], run_id="pending")
    snapshot = measurement.snapshot()
    assert snapshot["calls"][0]["success"] is False
    assert snapshot["calls"][0]["error_type"] == "ValueError"
    assert snapshot["calls_with_unknown_usage"] == 2
    assert snapshot["unfinished_generation_calls"] == 1
    assert "secret-api-key" not in json.dumps(snapshot)


def test_retrieval_failure_and_nested_scope_cleanup():
    outer = metrics.Measurements("outer")
    inner = metrics.Measurements("inner")
    with metrics.measurement_scope(outer):
        with metrics.measure_retrieval("documents"):
            pass
        with pytest.raises(ValueError):
            with metrics.measurement_scope(inner):
                with metrics.measure_retrieval("web"):
                    raise ValueError("failure")
        assert metrics.current_measurements.get() is outer
    assert metrics.current_measurements.get() is None
    assert outer.retrievals[0]["success"] is True
    assert inner.retrievals[0]["success"] is False
    assert inner.retrievals[0]["duration_seconds"] >= 0


@pytest.mark.parametrize("provider", ["openai", "google"])
def test_model_factory_attaches_request_callback(monkeypatch, provider):
    settings = Settings(_env_file=None, openai_api_key="fake", google_api_key="fake",
                        research_provider=provider, research_model="mock-model")
    monkeypatch.setattr(llm, "get_settings", lambda: settings)
    model = SimpleNamespace()
    constructor = Mock(return_value=model)
    monkeypatch.setattr(llm, "ChatOpenAI", constructor)
    monkeypatch.setattr(llm, "ChatGoogleGenerativeAI", constructor)
    measurement = metrics.Measurements("factory")
    with metrics.measurement_scope(measurement):
        assert llm.get_agent_llm("research") is model
    assert model.callbacks == [measurement]
    assert model.metadata == {"agent": "research", "provider": provider,
                              "ls_model_name": "mock-model"}


@pytest.mark.asyncio
async def test_langchain_invocation_delivers_callbacks_once():
    measurement = metrics.Measurements("langchain")
    model = FakeListChatModel(responses=["Offline response"], callbacks=[measurement],
                              metadata={"agent": "code", "provider": "fake"})
    await model.ainvoke("Offline question")
    snapshot = measurement.snapshot()
    assert snapshot["generation_calls"] == 1
    assert snapshot["calls"][0]["success"] is True
    assert snapshot["calls"][0]["agent"] == "code"
    assert snapshot["calls_with_unknown_usage"] == 1
