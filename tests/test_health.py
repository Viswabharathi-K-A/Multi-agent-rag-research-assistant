
import asyncio
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "ok"
    assert "application" in payload
    assert "environment" in payload


def test_homepage():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Multi-Agent Research Assistant" in response.text


def test_static_page_is_self_contained():
    with TestClient(app) as client:
        response = client.get("/static/index.html")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<style>" in response.text
    assert "<script>" in response.text
    assert '<script src=' not in response.text
    assert 'rel="stylesheet"' not in response.text


def test_invalid_route():
    with TestClient(app) as client:
        response = client.get("/nonexistent")

    assert response.status_code == 404


def test_embedding_model_is_initialized_before_requests(startup_embeddings):
    with TestClient(app) as client:
        startup_embeddings.assert_called_once_with(main.settings.embedding_model)
        assert client.get("/health").status_code == 200


@pytest.mark.asyncio
async def test_startup_waits_for_embeddings_without_blocking_event_loop(startup_embeddings):
    started = Event()
    release = Event()

    def load_model(model_name):
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError("Test did not release the model loader")

    startup_embeddings.side_effect = load_model
    lifespan = main.lifespan(app)
    startup = asyncio.create_task(lifespan.__aenter__())
    try:
        assert await asyncio.to_thread(started.wait, 5)
        assert not startup.done()
    finally:
        release.set()
        await asyncio.wait_for(startup, timeout=5)
        await lifespan.__aexit__(None, None, None)


def test_embedding_initialization_failure_prevents_startup(startup_embeddings):
    startup_embeddings.side_effect = RuntimeError("Embedding assets unavailable")

    with pytest.raises(RuntimeError, match="Embedding assets unavailable"):
        with TestClient(app):
            pytest.fail("Application started despite embedding initialization failure")
