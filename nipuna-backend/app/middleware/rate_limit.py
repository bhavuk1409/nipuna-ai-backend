from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import get_settings


def setup_rate_limiting(app: FastAPI) -> Limiter:
    settings = get_settings()

    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri=settings.redis_url if settings.is_production else None,
        enabled=settings.is_production,
    )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(_request: Request, _exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again in 60 seconds."},
        )

    return limiter
