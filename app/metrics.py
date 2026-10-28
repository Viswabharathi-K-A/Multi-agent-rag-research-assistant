"""Request-scoped evaluation measurements; never record prompts, keys, or answers."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter

from langchain_core.callbacks import BaseCallbackHandler


current_measurements = ContextVar("current_measurements", default=None)


class Measurements(BaseCallbackHandler):
    """Capture application model invocations, reported usage, and retrieval time."""

    run_inline = True

    def __init__(self, request_id: str):
        self.request_id = request_id
        self.started = perf_counter()
        self.first_worker_token_seconds = None
        self.outcome = "interrupted"
        self.calls = []
        self.retrievals = []
        self.pending = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs):
        metadata = metadata or {}
        call = {"agent": metadata.get("agent"), "provider": metadata.get("provider"),
                "model": metadata.get("ls_model_name"), "success": None,
                "input_tokens": None, "output_tokens": None,
                "first_token_seconds": None, "duration_seconds": None}
        self.calls.append(call)
        self.pending[run_id] = (perf_counter(), call)

    def on_llm_new_token(self, token, *, run_id, **kwargs):
        if token and run_id in self.pending:
            started, call = self.pending[run_id]
            if call["first_token_seconds"] is None:
                call["first_token_seconds"] = perf_counter() - started

    def on_llm_end(self, response, *, run_id, **kwargs):
        if run_id not in self.pending:
            return
        started, call = self.pending.pop(run_id)
        call.update(success=True, duration_seconds=perf_counter() - started)
        generations = response.generations
        message = getattr(generations[0][0], "message", None) if generations and generations[0] else None
        usage = getattr(message, "usage_metadata", None) or (response.llm_output or {}).get("token_usage") or {}
        call["input_tokens"] = usage.get("input_tokens", usage.get("prompt_tokens"))
        call["output_tokens"] = usage.get("output_tokens", usage.get("completion_tokens"))

    def on_llm_error(self, error, *, run_id, **kwargs):
        if run_id in self.pending:
            started, call = self.pending.pop(run_id)
            call.update(success=False, duration_seconds=perf_counter() - started,
                        error_type=type(error).__name__)

    def snapshot(self) -> dict:
        return {
            "request_id": self.request_id, "outcome": self.outcome,
            "server_duration_seconds": perf_counter() - self.started,
            "server_ttft_seconds": self.first_worker_token_seconds,
            "generation_calls": len(self.calls),
            "unfinished_generation_calls": len(self.pending),
            "generation_seconds": sum(call["duration_seconds"] or 0 for call in self.calls),
            "retrieval_seconds": sum(item["duration_seconds"] for item in self.retrievals),
            "known_input_tokens": sum(call["input_tokens"] or 0 for call in self.calls),
            "known_output_tokens": sum(call["output_tokens"] or 0 for call in self.calls),
            "calls_with_unknown_usage": sum(call["input_tokens"] is None or call["output_tokens"] is None
                                            for call in self.calls),
            "calls": self.calls, "retrievals": self.retrievals,
        }


@contextmanager
def measurement_scope(measurements: Measurements):
    token = current_measurements.set(measurements)
    try:
        yield
    finally:
        current_measurements.reset(token)


@contextmanager
def measure_retrieval(kind: str):
    measurements = current_measurements.get()
    if measurements is None:
        yield
        return
    started = perf_counter()
    item = {"kind": kind, "success": False}
    try:
        yield
        item["success"] = True
    finally:
        item["duration_seconds"] = perf_counter() - started
        measurements.retrievals.append(item)
