"""DEPRECATED: OpenSearch Serverless vector store.

This module is kept only as a stub for the planned future
"tier-2" cross-org vector search. The primary RAG path is now
``app.services.ai.pgvector_store``. New code must use
``pgvector_store`` directly.

Do not import this module from anywhere except
``app.services.ai.vector_store`` (the facade). The facade is the
only consumer and it only delegates here when
``settings.opensearch_enabled`` is True (default False).
"""

import warnings

warnings.warn(
    "app.services.ai._legacy_opensearch is deprecated. "
    "Use app.services.ai.pgvector_store instead.",
    DeprecationWarning,
    stacklevel=2,
)

from uuid import UUID  # noqa: E402  (kept for legacy import compat)

__all__: list[str] = []
