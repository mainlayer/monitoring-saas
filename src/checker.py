"""
HTTP health checker for the monitoring SaaS.

Performs async HTTP(S) checks against monitored URLs and returns structured results.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from .models import MetricDataPoint, Monitor, MonitorStatus, MonitorType

logger = logging.getLogger(__name__)

# Maximum concurrent checks across all monitors
_MAX_CONCURRENCY = 50
_semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)


async def check_monitor(monitor: Monitor) -> MetricDataPoint:
    """
    Run a single health check for the given monitor.

    Returns a MetricDataPoint describing the result.
    """
    async with _semaphore:
        if monitor.monitor_type == MonitorType.HTTP:
            return await _check_http(monitor)
        elif monitor.monitor_type == MonitorType.TCP:
            return await _check_tcp(monitor)
        else:
            # PING — fall back to a lightweight HTTP GET
            return await _check_http(monitor)


async def _check_http(monitor: Monitor) -> MetricDataPoint:
    """Perform an HTTP/HTTPS check and return a metric data point."""
    start = time.monotonic()
    status_code: Optional[int] = None
    is_up = False
    region = monitor.regions[0] if monitor.regions else "us-east-1"

    try:
        async with httpx.AsyncClient(
            timeout=monitor.timeout_seconds,
            follow_redirects=True,
        ) as client:
            resp = await client.get(monitor.url)
            status_code = resp.status_code

        elapsed_ms = (time.monotonic() - start) * 1000

        expected = monitor.expected_status_code or 200
        is_up = (status_code == expected) or (
            monitor.expected_status_code is None and 200 <= status_code < 400
        )

    except httpx.TimeoutException:
        elapsed_ms = monitor.timeout_seconds * 1000.0
        logger.warning("Monitor %s timed out", monitor.id)
    except httpx.RequestError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.warning("Monitor %s request error: %s", monitor.id, exc)

    return MetricDataPoint(
        timestamp=datetime.now(tz=timezone.utc),
        response_time_ms=elapsed_ms,
        status_code=status_code,
        region=region,
        is_up=is_up,
    )


async def _check_tcp(monitor: Monitor) -> MetricDataPoint:
    """Perform a TCP connectivity check."""
    start = time.monotonic()
    is_up = False
    region = monitor.regions[0] if monitor.regions else "us-east-1"

    # Parse host:port from URL-like string
    raw = monitor.url.replace("tcp://", "").replace("//", "")
    if ":" in raw:
        host, port_str = raw.rsplit(":", 1)
        port = int(port_str)
    else:
        host = raw
        port = 80

    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=monitor.timeout_seconds,
        )
        writer.close()
        await writer.wait_closed()
        is_up = True
    except (asyncio.TimeoutError, OSError) as exc:
        logger.warning("TCP check failed for %s: %s", monitor.url, exc)

    elapsed_ms = (time.monotonic() - start) * 1000
    return MetricDataPoint(
        timestamp=datetime.now(tz=timezone.utc),
        response_time_ms=elapsed_ms,
        status_code=None,
        region=region,
        is_up=is_up,
    )


async def run_checks(monitors: List[Monitor]) -> dict[str, MetricDataPoint]:
    """
    Run health checks for multiple monitors concurrently.

    Returns a mapping of monitor_id -> MetricDataPoint.
    """
    active = [m for m in monitors if m.is_active]
    if not active:
        return {}

    tasks = [check_monitor(m) for m in active]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    outcome: dict[str, MetricDataPoint] = {}
    for monitor, result in zip(active, results):
        if isinstance(result, Exception):
            logger.error("Unexpected error checking monitor %s: %s", monitor.id, result)
            outcome[monitor.id] = MetricDataPoint(
                timestamp=datetime.now(tz=timezone.utc),
                response_time_ms=0.0,
                status_code=None,
                region=monitor.regions[0] if monitor.regions else "us-east-1",
                is_up=False,
            )
        else:
            outcome[monitor.id] = result

    return outcome


def derive_status(point: MetricDataPoint) -> MonitorStatus:
    """Convert a MetricDataPoint to a MonitorStatus enum value."""
    if not point.is_up:
        return MonitorStatus.DOWN
    if point.response_time_ms > 3000:
        return MonitorStatus.DEGRADED
    return MonitorStatus.UP
