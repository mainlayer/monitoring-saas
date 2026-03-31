"""
Monitoring SaaS — FastAPI application.

Endpoints:
  POST /monitors          Create a new monitor
  GET  /monitors          List all monitors for the authenticated user
  GET  /status/{id}       Get latest status for a specific monitor
  GET  /health            Health check (unauthenticated)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Path, Query, status
from fastapi.middleware.cors import CORSMiddleware

from .billing import require_subscription
from .checker import check_monitor, derive_status
from .models import (
    Monitor,
    MonitorCreate,
    MonitorStatus,
    MonitorStatusResponse,
    PaginatedResponse,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Monitoring SaaS",
    description="Uptime monitoring with Mainlayer subscription billing.",
    version="1.0.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory store (replace with a real DB in production)
# ---------------------------------------------------------------------------
_monitors: Dict[str, Monitor] = {}
_check_history: Dict[str, list] = {}  # monitor_id -> list of MetricDataPoint


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "ok", "monitor_count": len(_monitors)}


@app.post(
    "/monitors",
    response_model=Monitor,
    status_code=status.HTTP_201_CREATED,
    tags=["monitors"],
    summary="Create a new monitor",
)
async def create_monitor(
    payload: MonitorCreate,
    token: str = Depends(require_subscription),
) -> Monitor:
    """
    Create an uptime monitor for the given URL.

    Requires an active Mainlayer subscription (Bearer token).
    """
    monitor = Monitor(
        name=payload.name,
        url=payload.url,
        monitor_type=payload.monitor_type,
        interval_seconds=payload.interval_seconds,
        timeout_seconds=payload.timeout_seconds,
        expected_status_code=payload.expected_status_code,
        regions=payload.regions,
        owner_id=token[:16],  # use first 16 chars of token as owner ref
    )
    _monitors[monitor.id] = monitor
    _check_history[monitor.id] = []
    logger.info("Monitor created: %s (%s)", monitor.id, monitor.url)
    return monitor


@app.get(
    "/monitors",
    response_model=PaginatedResponse,
    tags=["monitors"],
    summary="List all monitors",
)
async def list_monitors(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    token: str = Depends(require_subscription),
) -> PaginatedResponse:
    """
    Return a paginated list of all monitors owned by the authenticated user.
    """
    owner_prefix = token[:16]
    owned = [m for m in _monitors.values() if m.owner_id == owner_prefix]
    total = len(owned)
    start = (page - 1) * per_page
    page_items = owned[start : start + per_page]

    return PaginatedResponse(
        items=[m.model_dump() for m in page_items],
        total=total,
        page=page,
        per_page=per_page,
    )


@app.get(
    "/status/{monitor_id}",
    response_model=MonitorStatusResponse,
    tags=["monitors"],
    summary="Get the latest status for a monitor",
)
async def get_monitor_status(
    monitor_id: str = Path(..., description="Monitor ID"),
    token: str = Depends(require_subscription),
) -> MonitorStatusResponse:
    """
    Run an on-demand health check and return the current status.
    """
    monitor = _monitors.get(monitor_id)
    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor {monitor_id!r} not found.",
        )

    owner_prefix = token[:16]
    if monitor.owner_id != owner_prefix:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your monitor.")

    # Run a live check
    point = await check_monitor(monitor)
    _check_history[monitor_id].append(point)

    # Keep history bounded
    if len(_check_history[monitor_id]) > 1440:
        _check_history[monitor_id] = _check_history[monitor_id][-1440:]

    # Update stored status
    monitor.status = derive_status(point)
    monitor.updated_at = datetime.now(tz=timezone.utc)

    # Calculate 24-h uptime from history
    history = _check_history[monitor_id]
    uptime = (
        sum(1 for p in history if p.is_up) / len(history) * 100
        if history
        else 100.0
    )

    return MonitorStatusResponse(
        monitor_id=monitor_id,
        name=monitor.name,
        url=monitor.url,
        status=monitor.status,
        last_checked_at=point.timestamp,
        uptime_percentage_24h=round(uptime, 2),
        response_time_ms=point.response_time_ms if point.is_up else None,
        checked_from_regions=monitor.regions,
    )


@app.delete(
    "/monitors/{monitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["monitors"],
    summary="Delete a monitor",
)
async def delete_monitor(
    monitor_id: str = Path(...),
    token: str = Depends(require_subscription),
) -> None:
    monitor = _monitors.get(monitor_id)
    if not monitor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found.")
    if monitor.owner_id != token[:16]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your monitor.")
    del _monitors[monitor_id]
    _check_history.pop(monitor_id, None)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
