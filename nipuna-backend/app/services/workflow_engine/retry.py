"""Retry decorator for workflow engine handlers.

Wraps a coroutine function with exponential backoff. Used to give flaky
network integrations (Gmail, Slack, Tally, etc.) a few chances to recover
from transient errors before the engine records a hard failure.

NOTE: this is an in-process asyncio sleep — it only retries within a single
workflow run. It is *not* a distributed / durable retry; the worker that
invokes the engine still owns the at-least-once delivery guarantee.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Awaitable, Callable, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Return a decorator that retries the wrapped coroutine on failure.

    On exception we log a warning, sleep `base_delay * 2 ** (attempt - 1)`
    seconds, and try again. After `max_attempts` we re-raise the last
    exception so the engine surfaces it as a normal node failure.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_exc: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:  # noqa: PERF203 — explicit for clarity
                    last_exc = exc
                    if attempt >= max_attempts:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            getattr(func, "__name__", "<handler>"),
                            attempt,
                            exc,
                        )
                        raise
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "%s attempt %d/%d failed: %s — retrying in %.2fs",
                        getattr(func, "__name__", "<handler>"),
                        attempt,
                        max_attempts,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
            # Unreachable — the loop either returns or re-raises — but mypy
            # is happier when we have an explicit terminal statement.
            assert last_exc is not None
            raise last_exc  # pragma: no cover

        return wrapper

    return decorator


__all__ = ["with_retry"]


def _typecheck() -> None:
    """Compile-time only — kept so `Any` stays imported in lint passes."""
    _: Any = None
