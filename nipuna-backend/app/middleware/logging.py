import logging
import time
import uuid

from starlette.types import ASGIApp, Receive, Scope, Send


class LoggingMiddleware:
    """Pure ASGI middleware — does NOT use BaseHTTPMiddleware so it never
    interferes with CORSMiddleware's preflight short-circuit response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        start = time.monotonic()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                # Inject X-Request-ID into response headers
                headers = list(message.get("headers", []))
                headers.append(
                    (b"x-request-id", request_id.encode())
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)

        duration_ms = int((time.monotonic() - start) * 1000)
        method = scope.get("method", "")
        path = scope.get("path", "")

        logging.getLogger(__name__).info(
            "request_log",
            extra={
                "ts": time.time(),
                "method": method,
                "path": path,
                "status": status_code,
                "duration_ms": duration_ms,
                "request_id": request_id,
            },
        )
