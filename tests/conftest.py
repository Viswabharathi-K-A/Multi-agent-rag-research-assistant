"""Keep application startup independent of local model assets in offline tests."""

from unittest.mock import Mock

import pytest

from app import main


@pytest.fixture(autouse=True)
def startup_embeddings(monkeypatch):
    """Mock only FastAPI's loader; retrieval tests retain their own boundaries."""
    loader = Mock()
    monkeypatch.setattr(main, "get_embeddings", loader)
    return loader
