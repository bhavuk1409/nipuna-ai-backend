"""Desktop app authentication endpoints."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

# API routes mounted under /api/v1/desktop
router = APIRouter(prefix="/desktop", tags=["desktop"])
# In-memory store: opaque_token -> { clerk_jwt, expires_at, user_id }
# SECURITY NOTE: For production, this in-memory store should be replaced with a
# shared/distributed store like Redis to support multiple app processes, handle
# state-based CSRF protection, and avoid state loss on server restarts.
# For local development, this in-memory store is acceptable.
_desktop_tokens: dict[str, dict[str, Any]] = {}


@router.post("/token")
async def issue_desktop_token(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Issues a short-lived (5 min) opaque token for the desktop app OAuth callback."""
    settings = get_settings()
    if settings.is_production:
        logger.warning("Using in-memory desktop token storage in a production environment! Redis is highly recommended.")
    now = time.time()
    # Purge expired tokens
    expired = [k for k, v in _desktop_tokens.items() if v["expires_at"] < now]
    for k in expired:
        del _desktop_tokens[k]

    auth_header = request.headers.get("authorization", "")
    clerk_jwt = auth_header.removeprefix("Bearer ").strip()

    opaque_token = uuid.uuid4().hex
    _desktop_tokens[opaque_token] = {
        "clerk_jwt": clerk_jwt,
        "expires_at": now + 300,
        "user_id": str(user.id),
    }
    logger.info("Issued desktop token for user %s", user.id)
    return {"token": opaque_token}


class ExchangeRequest(BaseModel):
    token: str


@router.post("/exchange")
async def exchange_desktop_token(body: ExchangeRequest) -> dict:
    """Exchanges a one-time opaque token for the Clerk JWT. Used by the desktop app."""
    stored = _desktop_tokens.get(body.token)
    if not stored:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if stored["expires_at"] < time.time():
        del _desktop_tokens[body.token]
        raise HTTPException(status_code=401, detail="Token expired")
    del _desktop_tokens[body.token]  # one-time use
    logger.info("Desktop token exchanged for user %s", stored["user_id"])
    return {"clerk_jwt": stored["clerk_jwt"]}
