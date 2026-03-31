"""Tests for the monitoring SaaS FastAPI application."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.models import MonitorStatus


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clear_store():
    """Reset the in-memory store before each test."""
    from src.main import _monitors, _check_history

    _monitors.clear()
    _check_history.clear()
    yield
    _monitors.clear()
    _check_history.clear()


def _auth_headers(token: str = "test-token-abcdefghij") -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /monitors
# ---------------------------------------------------------------------------


def test_create_monitor_requires_auth(client):
    resp = client.post(
        "/monitors",
        json={"name": "Test", "url": "https://example.com"},
    )
    assert resp.status_code in (401, 403, 422)


@patch("src.billing.verify_access", new_callable=AsyncMock, return_value=True)
def test_create_monitor_success(mock_verify, client):
    resp = client.post(
        "/monitors",
        json={
            "name": "My Monitor",
            "url": "https://example.com",
            "monitor_type": "http",
            "interval_seconds": 60,
            "timeout_seconds": 10,
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Monitor"
    assert data["url"] == "https://example.com"
    assert "id" in data


# ---------------------------------------------------------------------------
# GET /monitors
# ---------------------------------------------------------------------------


@patch("src.billing.verify_access", new_callable=AsyncMock, return_value=True)
def test_list_monitors(mock_verify, client):
    # Create two monitors
    for name in ("Alpha", "Beta"):
        client.post(
            "/monitors",
            json={"name": name, "url": f"https://{name.lower()}.example.com"},
            headers=_auth_headers(),
        )

    resp = client.get("/monitors", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


# ---------------------------------------------------------------------------
# GET /status/{id}
# ---------------------------------------------------------------------------


@patch("src.billing.verify_access", new_callable=AsyncMock, return_value=True)
@patch(
    "src.main.check_monitor",
    new_callable=AsyncMock,
)
def test_get_status(mock_check, mock_verify, client):
    from src.models import MetricDataPoint
    from datetime import datetime, timezone

    mock_check.return_value = MetricDataPoint(
        timestamp=datetime.now(tz=timezone.utc),
        response_time_ms=120.0,
        status_code=200,
        region="us-east-1",
        is_up=True,
    )

    # Create a monitor first
    resp = client.post(
        "/monitors",
        json={"name": "Checked", "url": "https://example.com"},
        headers=_auth_headers(),
    )
    monitor_id = resp.json()["id"]

    # Poll status
    resp = client.get(f"/status/{monitor_id}", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == MonitorStatus.UP
    assert data["response_time_ms"] == pytest.approx(120.0)


def test_status_not_found(client):
    with patch("src.billing.verify_access", new_callable=AsyncMock, return_value=True):
        resp = client.get("/status/nonexistent-id", headers=_auth_headers())
    assert resp.status_code == 404
