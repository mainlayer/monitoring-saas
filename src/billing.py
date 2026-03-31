"""
Billing middleware for the monitoring SaaS.

Uses Mainlayer to verify a subscription token before allowing API access.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

MAINLAYER_BASE_URL = os.getenv("MAINLAYER_BASE_URL", "https://api.mainlayer.fr")
MAINLAYER_API_KEY = os.getenv("MAINLAYER_API_KEY", "")
MAINLAYER_RESOURCE_ID = os.getenv("MAINLAYER_RESOURCE_ID", "")

_TIMEOUT = 10.0
_bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def _headers() -> dict[str, str]:
    if not MAINLAYER_API_KEY:
        raise RuntimeError("MAINLAYER_API_KEY is not set")
    return {
        "Authorization": f"Bearer {MAINLAYER_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "monitoring-saas/1.0",
    }


async def verify_access(token: str) -> bool:
    """Return True if `token` is authorised for the configured resource."""
    if not MAINLAYER_RESOURCE_ID or not MAINLAYER_API_KEY:
        logger.warning("Mainlayer not configured — allowing access in dev mode")
        return True

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(
                f"{MAINLAYER_BASE_URL}/resources/{MAINLAYER_RESOURCE_ID}/verify",
                json={"token": token},
                headers=_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                return bool(data.get("authorized", False))
            return False
        except httpx.RequestError as exc:
            logger.error("Mainlayer unreachable: %s", exc)
            # Fail open in dev; fail closed in prod — controlled via env flag
            return os.getenv("MAINLAYER_FAIL_OPEN", "true").lower() == "true"


async def require_subscription(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> str:
    """
    FastAPI dependency that checks a Mainlayer subscription token.

    Usage::

        @app.get("/monitors")
        async def list_monitors(user: str = Depends(require_subscription)):
            ...
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Use: Bearer <mainlayer-token>",
        )

    token = credentials.credentials
    authorised = await verify_access(token)
    if not authorised:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Active Mainlayer subscription required. See https://mainlayer.fr",
        )
    return token


async def optional_subscription(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> str | None:
    """Like require_subscription but does not raise — returns None for free tier."""
    if credentials is None:
        return None
    authorised = await verify_access(credentials.credentials)
    return credentials.credentials if authorised else None
