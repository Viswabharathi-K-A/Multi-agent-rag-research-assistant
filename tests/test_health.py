
from fastapi.testclient import TestClient

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


def test_static_stylesheet():
    with TestClient(app) as client:
        response = client.get("/static/style.css")

    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


def test_invalid_route():
    with TestClient(app) as client:
        response = client.get("/nonexistent")

    assert response.status_code == 404
