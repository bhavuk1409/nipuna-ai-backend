"""JWKS cache — fetches Clerk public keys once per hour, reuses cached value."""

from __future__ import annotations

import time
import logging
import asyncio
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_jwks_cache: dict[str, Any] = {}
_jwks_fetched_at: float = 0.0
_CACHE_TTL = 3600.0


async def get_jwks() -> dict[str, Any]:
    global _jwks_cache, _jwks_fetched_at

    now = time.monotonic()
    if _jwks_cache and (now - _jwks_fetched_at) < _CACHE_TTL:
        return _jwks_cache

    settings = get_settings()
    clerk_domain = settings.clerk_domain
    if not clerk_domain:
        raise RuntimeError("CLERK_DOMAIN is not configured")

    url = f"https://{clerk_domain}/.well-known/jwks.json"
    data = None
    last_error = None

    # Retry logic: 2 attempts with 1 second delay
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                break
        except httpx.HTTPError as exc:
            last_error = exc
            logger.warning("JWKS fetch attempt %d failed: %s", attempt + 1, exc)
            if attempt < 1:
                await asyncio.sleep(1.0)

    if data:
        _jwks_cache = data
        _jwks_fetched_at = now
        logger.info("JWKS refreshed from %s", url)
        return _jwks_cache

    # Graceful degradation if fetch failed but we have a cache
    if _jwks_cache:
        logger.warning(
            "Failed to fetch JWKS from %s. Using cached keys (expired %s seconds ago). Error: %s",
            url,
            int(now - _jwks_fetched_at - _CACHE_TTL),
            last_error,
        )
        return _jwks_cache

    raise RuntimeError(f"Failed to fetch JWKS from {url} and no cached keys available. Error: {last_error}")
