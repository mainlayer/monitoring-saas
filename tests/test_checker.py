"""Tests for the HTTP health checker."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.checker import check_monitor, derive_status, run_checks
from src.models import MetricDataPoint, Monitor, MonitorStatus, MonitorType


def _make_monitor(**kwargs) -> Monitor:
    defaults = dict(
        name="Test Monitor",
        url="https://example.com",
        monitor_type=MonitorType.HTTP,
        interval_seconds=60,
        timeout_seconds=10,
        expected_status_code=200,
        regions=["us-east-1"],
    )
    defaults.update(kwargs)
    return Monitor(**defaults)


# ---------------------------------------------------------------------------
# derive_status
# ---------------------------------------------------------------------------


def _point(is_up: bool, response_ms: float = 100.0) -> MetricDataPoint:
    return MetricDataPoint(
        timestamp=datetime.now(tz=timezone.utc),
        response_time_ms=response_ms,
        status_code=200 if is_up else None,
        region="us-east-1",
        is_up=is_up,
    )


def test_derive_status_up():
    assert derive_status(_point(True, 100)) == MonitorStatus.UP


def test_derive_status_down():
    assert derive_status(_point(False)) == MonitorStatus.DOWN


def test_derive_status_degraded():
    assert derive_status(_point(True, 4000)) == MonitorStatus.DEGRADED


# ---------------------------------------------------------------------------
# check_monitor (HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_monitor_success():
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("src.checker.httpx.AsyncClient", return_value=mock_client):
        monitor = _make_monitor()
        point = await check_monitor(monitor)

    assert point.is_up is True
    assert point.status_code == 200


@pytest.mark.asyncio
async def test_check_monitor_timeout():
    import httpx as _httpx

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=_httpx.TimeoutException("timed out"))

    with patch("src.checker.httpx.AsyncClient", return_value=mock_client):
        monitor = _make_monitor()
        point = await check_monitor(monitor)

    assert point.is_up is False


# ---------------------------------------------------------------------------
# run_checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_checks_skips_inactive():
    monitor = _make_monitor(is_active=False)
    result = await run_checks([monitor])
    assert result == {}


@pytest.mark.asyncio
async def test_run_checks_returns_all():
    monitors = [_make_monitor(url=f"https://site{i}.example.com") for i in range(3)]

    fake_point = MetricDataPoint(
        timestamp=datetime.now(tz=timezone.utc),
        response_time_ms=50.0,
        status_code=200,
        region="us-east-1",
        is_up=True,
    )

    with patch("src.checker.check_monitor", new_callable=AsyncMock, return_value=fake_point):
        results = await run_checks(monitors)

    assert len(results) == 3
    for m in monitors:
        assert m.id in results
