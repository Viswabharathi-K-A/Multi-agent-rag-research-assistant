"""Real supervisor and LangGraph routing with a fake model and research worker."""

from unittest.mock import AsyncMock, Mock

import pytest

from app import llm
from app.agents import agents, supervisor
from app.config import Settings


@pytest.mark.asyncio
async def test_supervisor_delegates_and_finishes(monkeypatch):
    decisions = AsyncMock(side_effect=[
        supervisor.SupervisorDecision(
            next_agent="research", instruction="Explain Raft", reason="Research is needed"),
        supervisor.SupervisorDecision(
            next_agent="finish", instruction="", reason="Research is complete",
            final_answer="Raft uses leader election."),
    ])
    model = Mock()
    model.with_structured_output.return_value.ainvoke = decisions
    monkeypatch.setattr(llm, "get_agent_llm", lambda role: model)
    monkeypatch.setattr(supervisor, "get_settings", lambda: Settings(_env_file=None))
    result = {
        "agent": "research", "instruction": "Explain Raft",
        "content": "Raft uses leader election.", "success": True,
        "error": None, "sources": [],
    }

    async def research(state):
        assert state["current_task"]["agent"] == "research"
        assert state["current_task"]["instruction"] == "Explain Raft"
        return {"results": [result]}

    monkeypatch.setattr(agents, "research_node", research)
    output = await agents.build_agent_graph().ainvoke({
        "user_query": "Explain Raft", "iteration": 0, "max_iterations": 4,
    })

    assert output["results"] == [result]
    assert output["next_agent"] == "finish"
    assert output["final_answer"] == "Raft uses leader election."
    assert decisions.await_count == 2
