"""Shared client that skips embedding downloads during application startup."""

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "get_embeddings", lambda model_name: None)
    with TestClient(main.app) as client:
        yield client
