from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.middleware.logging import LoggingMiddleware
from app.middleware.rate_limit import setup_rate_limiting
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import api_router
from app.services.notifications.schema import ensure_alert_schema

logger = logging.getLogger(__name__)

settings = get_settings()

CORS_ALLOWED_ORIGINS = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://app.nipunaai.in",
    "https://nipunaai.in",
    "https://www.nipunaai.in",
]

# Merge with configurable CORS_EXTRA_ORIGINS from settings
if settings.cors_extra_origins:
    extra_origins = [orig.strip() for orig in settings.cors_extra_origins.split(",") if orig.strip()]
    CORS_ALLOWED_ORIGINS.extend(extra_origins)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting Nipuna AI Backend. Active auth domain: '%s'", settings.clerk_domain)
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.env,
            traces_sample_rate=0.0,
        )

    async with engine.begin() as connection:
        await connection.execute(text("SELECT 1"))
        await connection.run_sync(ensure_alert_schema)

    yield
    await engine.dispose()


app = FastAPI(
    title="Nipuna AI",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler that ensures CORS headers are always present on 500s.
    Without this, unhandled exceptions can bypass CORSMiddleware and the browser
    sees a CORS violation instead of the actual error."""
    logger.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    origin = request.headers.get("origin", "")
    headers: dict[str, str] = {}
    if origin in CORS_ALLOWED_ORIGINS:
        headers["access-control-allow-origin"] = origin
        headers["access-control-allow-credentials"] = "true"
        headers["access-control-expose-headers"] = "*"
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers=headers,
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(LoggingMiddleware)

limiter = setup_rate_limiting(app)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(api_router, prefix="/api/v1")


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    return {
        "service": "Nipuna AI Backend",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "env": settings.env}
