from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
from app.routers.desktop import page_router as desktop_page_router


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.env,
            traces_sample_rate=0.0,
        )

    async with engine.begin() as connection:
        await connection.execute(text("SELECT 1"))

    yield
    await engine.dispose()


app = FastAPI(
    title="Nipuna AI",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://app.nipunaai.in",
        "https://nipunaai.in",
        "https://www.nipunaai.in",
        "http://127.0.0.1:41731",
    ],
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
app.include_router(desktop_page_router)


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


# CI/CD trigger comment
