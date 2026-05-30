from starlette.types import ASGIApp, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Pure ASGI middleware — does NOT use BaseHTTPMiddleware so it never
    interferes with CORSMiddleware's preflight short-circuit response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # OPTIONS preflights must pass through untouched so CORSMiddleware
        # can short-circuit with its 200 response.
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                ]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
