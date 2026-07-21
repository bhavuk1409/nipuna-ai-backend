"""Embedding client — single source of truth for ``RAG_ENABLED``.

Behaviour:
  1. Uses OpenAI ``text-embedding-3-small`` (1536 dim) when
     ``OPENAI_API_KEY`` is configured.
  2. Returns an empty list if no embedding provider is configured —
     callers treat this as "skip RAG". The pipeline still works; it
     just runs without knowledge-base context.

The model swap from ``text-embedding-ada-002`` is intentional:
``text-embedding-3-small`` is cheaper, higher-quality, and OpenAI's
recommended default for new projects. Both models emit 1536-d
embeddings, so the existing ``vector(1536)`` schema doesn't change.
"""

from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def _has_openai(self) -> bool:
        return bool(self._settings.openai_api_key)

    @property
    def enabled(self) -> bool:
        """Single source of truth for the "is RAG wired up?" question.

        Returns True only when we have an embedding provider
        configured. The pipeline reads this to decide whether to
        attempt a vector search at all.
        """
        return self._has_openai

    async def embed(self, text: str) -> list[float]:
        """Return a 1536-d embedding for ``text``.

        Returns ``[]`` (empty list) when no embedding provider is
        configured — callers should treat this as "skip RAG".
        """
        if not text:
            return []

        if self._has_openai:
            try:
                return await self._embed_openai(text)
            except Exception as exc:
                logger.warning("OpenAI embedding failed: %s", exc)
                return []

        # No provider — skip silently. We log at debug because this
        # is the common case in dev where OPENAI_API_KEY is unset.
        logger.debug("No embedding provider configured. Skipping RAG.")
        return []

    async def _embed_openai(self, text: str) -> list[float]:
        import httpx

        api_key = self._settings.openai_api_key
        # text-embedding-3-small — pinned to 1536 dim via the
        # ``dimensions`` parameter so the column doesn't drift even
        # if OpenAI changes the default.
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "text-embedding-3-small",
                    "input": text,
                    "dimensions": 1536,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]


embedding_client = EmbeddingClient()
