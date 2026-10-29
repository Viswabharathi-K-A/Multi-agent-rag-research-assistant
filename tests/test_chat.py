"""Invalid input must be rejected before starting agent work."""

from unittest.mock import Mock

from app import main


def test_empty_query_is_rejected(client, monkeypatch):
    graph = Mock(side_effect=AssertionError("Invalid input must not start the graph"))
    monkeypatch.setattr(main, "build_agent_graph", graph)

    response = client.post("/chat", json={"query": ""})

    assert response.status_code == 422
    graph.assert_not_called()
