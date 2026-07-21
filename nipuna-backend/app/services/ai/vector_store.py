"""Vector store facade.

The primary RAG path is now ``app.services.ai.pgvector_store``. This
module exists as a thin facade so the singleton import in
``app.routers.chat`` keeps working without a session-parameter
rewrite. New code should import ``pgvector_store`` directly and pass
the session explicitly.

The OpenSearch Serverless code is gone from the live path. The
deprecated stub lives in ``_legacy_opensearch`` and is never imported
unless an operator sets ``OPENSEARCH_ENABLED=true`` in the future.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.services.ai import pgvector_store

logger = logging.getLogger(__name__)


class VectorStore:
    """Compat shim — the real work is in ``pgvector_store``.

    The OpenSearch implementation is gone. The class exists only to
    keep ``app.routers.chat`` importable. New code should call
    ``pgvector_store.upsert`` / ``pgvector_store.search`` directly
    with the request-scoped session.
    """

    def __init__(self) -> None:
        self._impl = pgvector_store

    async def upsert(
        self,
        org_id: str | UUID,
        doc_id: str,
        text: str,
        embedding: list[float],
    ) -> None:
        raise RuntimeError(
            "vector_store.upsert is a compat shim. "
            "Use pgvector_store.upsert(db=..., org_id=..., ...) directly."
        )

    async def search(
        self,
        org_id: str | UUID,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        raise RuntimeError(
            "vector_store.search is a compat shim. "
            "Use pgvector_store.search(db=..., org_id=..., ...) directly."
        )


# Backwards-compat singleton. Imports that only need the type still
# resolve; the methods raise so any *call* surfaces a clear migration
# message instead of silently using a dead path.
vector_store = VectorStore()


__all__ = ["VectorStore", "vector_store"]
