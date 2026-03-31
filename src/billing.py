"""
Billing middleware for the monitoring SaaS.

Uses Mainlayer to verify a subscription token before allowing API access.
Includes token verification caching to reduce API calls.
"""
from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from typing import Dict, Optional, Tuple

import httpx
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

MAINLAYER_BASE_URL = os.getenv("MAINLAYER_BASE_URL", "https://api.mainlayer.fr")
MAINLAYER_API_KEY = os.getenv("MAINLAYER_API_KEY", "")
MAINLAYER_RESOURCE_ID = os.getenv("MAINLAYER_RESOURCE_ID", "")

_TIMEOUT = 10.0
_bearer = HTTPBearer(auto_error=False)
_CACHE_TTL = 300.0  # 5 minutes


class _VerificationCache:
    """In-memory cache for subscription token verification results."""

    def __init__(self, ttl: float = _CACHE_TTL):
        self._ttl = ttl
        self._cache: Dict[str, Tuple[bool, float]] = {}

    def get(self, token: str) -> Optional[bool]:
        """Return cached verification result if still valid."""
        entry = self._cache.get(token)
        if entry and time.monotonic() - entry[1] < self._ttl:
            return entry[0]
        return None

    def set(self, token: str, authorized: bool) -> None:
        """Store verification result in cache."""
        self._cache[token] = (authorized, time.monotonic())

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()


_verification_cache = _VerificationCache()


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
    """
    Verify if a token is authorized for the configured Mainlayer resource.
    Uses in-memory caching to reduce API calls (5 minute TTL).
    """
    if not MAINLAYER_RESOURCE_ID or not MAINLAYER_API_KEY:
        logger.warning("Mainlayer not configured — allowing access in dev mode")
        return True

    # Check cache first
    cached = _verification_cache.get(token)
    if cached is not None:
        return cached

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(
                f"{MAINLAYER_BASE_URL}/resources/{MAINLAYER_RESOURCE_ID}/verify",
                json={"token": token},
                headers=_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                authorized = bool(data.get("authorized", False))
                _verification_cache.set(token, authorized)
                logger.info("Token verified: %s", "authorized" if authorized else "denied")
                return authorized
            elif resp.status_code == 401:
                logger.warning("Token rejected by Mainlayer")
                _verification_cache.set(token, False)
                return False
            else:
                logger.warning("Unexpected status from Mainlayer: %d", resp.status_code)
                return False
        except httpx.RequestError as exc:
            logger.error("Mainlayer unreachable: %s", exc)
            # Fail open in dev; fail closed in prod — controlled via env flag
            fail_open = os.getenv("MAINLAYER_FAIL_OPEN", "true").lower() == "true"
            if fail_open:
                logger.warning("Mainlayer unavailable, failing open (dev mode)")
            return fail_open


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
