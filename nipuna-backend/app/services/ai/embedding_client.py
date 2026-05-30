"""Embedding client with graceful degradation.

Groq does NOT support embeddings — calling Groq's embedding endpoint returns 404.
This client:
  1. Uses OpenAI embeddings if OPENAI_API_KEY is configured.
  2. Falls back to a zero-vector (disabling RAG) if no embedding provider is available.
     The pipeline still works — it just runs without knowledge-base context.
"""

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def _has_openai(self) -> bool:
        return bool(self._settings.openai_api_key)

    async def embed(self, text: str) -> list[float]:
        """
        Return an embedding vector for `text`.
        Returns [] (empty list) if no embedding provider is configured —
        callers should treat [] as "skip RAG".
        """
        if self._has_openai:
            try:
                return await self._embed_openai(text)
            except Exception as exc:
                logger.warning("OpenAI embedding failed: %s", exc)
                return []

        # Groq doesn't support embeddings — skip silently instead of erroring
        logger.debug("No embedding provider configured (Groq does not support embeddings). Skipping RAG.")
        return []

    async def _embed_openai(self, text: str) -> list[float]:
        import httpx

        api_key = self._settings.openai_api_key
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": "text-embedding-ada-002", "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]


embedding_client = EmbeddingClient()
