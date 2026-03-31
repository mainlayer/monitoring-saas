"""
Domain models for the monitoring SaaS application.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MonitorStatus(str, Enum):
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class MonitorType(str, Enum):
    HTTP = "http"
    TCP = "tcp"
    PING = "ping"


class AlertChannel(str, Enum):
    EMAIL = "email"
    WEBHOOK = "webhook"
    SLACK = "slack"


class IncidentSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BillingPlan(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


# ---------------------------------------------------------------------------
# Monitor models
# ---------------------------------------------------------------------------


class MonitorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Human-readable monitor name")
    url: str = Field(..., description="Target URL or host to monitor")
    monitor_type: MonitorType = Field(MonitorType.HTTP, description="Protocol to use for checking")
    interval_seconds: int = Field(60, ge=30, le=3600, description="Check interval in seconds")
    timeout_seconds: int = Field(10, ge=1, le=60, description="Request timeout in seconds")
    expected_status_code: Optional[int] = Field(200, description="Expected HTTP status code (HTTP monitors only)")
    regions: List[str] = Field(default_factory=lambda: ["us-east-1"], description="Regions to run checks from")

    @validator("url")
    def validate_url(cls, v: str) -> str:  # noqa: N805
        v = v.strip()
        if not v:
            raise ValueError("URL must not be empty")
        return v


class Monitor(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    url: str
    monitor_type: MonitorType
    interval_seconds: int
    timeout_seconds: int
    expected_status_code: Optional[int]
    regions: List[str]
    status: MonitorStatus = MonitorStatus.UNKNOWN
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    owner_id: str = "default"
    is_active: bool = True


class MonitorStatusResponse(BaseModel):
    monitor_id: str
    name: str
    url: str
    status: MonitorStatus
    last_checked_at: Optional[datetime]
    uptime_percentage_24h: float
    response_time_ms: Optional[float]
    checked_from_regions: List[str]


# ---------------------------------------------------------------------------
# Incident models
# ---------------------------------------------------------------------------


class Incident(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    monitor_id: str
    severity: IncidentSeverity
    title: str
    description: str
    started_at: datetime
    resolved_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    is_resolved: bool = False


# ---------------------------------------------------------------------------
# Metrics models
# ---------------------------------------------------------------------------


class MetricDataPoint(BaseModel):
    timestamp: datetime
    response_time_ms: float
    status_code: Optional[int]
    region: str
    is_up: bool


class MonitorMetrics(BaseModel):
    monitor_id: str
    period_hours: int
    data_points: List[MetricDataPoint]
    avg_response_time_ms: float
    p95_response_time_ms: float
    p99_response_time_ms: float
    uptime_percentage: float
    total_checks: int
    successful_checks: int


# ---------------------------------------------------------------------------
# Alert models
# ---------------------------------------------------------------------------


class AlertConfig(BaseModel):
    monitor_id: str
    channel: AlertChannel
    destination: str = Field(..., description="Email address, webhook URL, or Slack webhook")
    notify_on_down: bool = True
    notify_on_recovery: bool = True
    notify_on_degraded: bool = False
    cooldown_minutes: int = Field(5, ge=1, le=60)


class AlertConfigResponse(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    monitor_id: str
    channel: AlertChannel
    destination: str
    notify_on_down: bool
    notify_on_recovery: bool
    notify_on_degraded: bool
    cooldown_minutes: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Billing models
# ---------------------------------------------------------------------------


class SubscribeRequest(BaseModel):
    plan: BillingPlan
    api_key: str = Field(..., description="Your Mainlayer API key")
    user_email: str = Field(..., description="Email for billing notifications")


class SubscribeResponse(BaseModel):
    success: bool
    plan: BillingPlan
    subscription_id: Optional[str]
    message: str
    features: List[str]


# ---------------------------------------------------------------------------
# Generic response models
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    upgrade_url: Optional[str] = None


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    per_page: int
