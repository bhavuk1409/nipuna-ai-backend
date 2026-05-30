import json
import logging
from uuid import UUID

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self) -> None:
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("opensearchserverless", region_name="ap-south-1")
        return self._client

    async def upsert(
        self,
        org_id: str | UUID,
        doc_id: str,
        text: str,
        embedding: list[float],
    ) -> None:
        index_name = f"nipuna-vectors-{org_id}"
        await self._ensure_index(org_id, len(embedding))

        import httpx
        from app.config import get_settings

        settings = get_settings()
        endpoint = await self._get_collection_endpoint()

        document = {
            "org_id": str(org_id),
            "doc_id": doc_id,
            "text": text,
            "embedding": embedding,
            "created_at": None,
        }

        async with httpx.AsyncClient() as client:
            try:
                await client.post(
                    f"{endpoint}/{index_name}/_doc/{doc_id}",
                    json=document,
                )
            except Exception as exc:
                logger.warning("Vector upsert failed: %s", exc)

    async def search(
        self,
        org_id: str | UUID,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        index_name = f"nipuna-vectors-{org_id}"
        from app.config import get_settings

        settings = get_settings()
        endpoint = await self._get_collection_endpoint()

        query = {
            "size": top_k,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": query_embedding,
                        "k": top_k,
                    }
                }
            },
        }

        import httpx

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{endpoint}/{index_name}/_search",
                    json=query,
                )
                resp.raise_for_status()
                data = resp.json()
                hits = data.get("hits", {}).get("hits", [])
                return [
                    {
                        "doc_id": h["_source"].get("doc_id"),
                        "text": h["_source"].get("text"),
                        "score": h["_score"],
                    }
                    for h in hits
                ]
            except Exception as exc:
                logger.warning("Vector search failed: %s", exc)
                return []

    async def _ensure_index(self, org_id: str | UUID, dimension: int) -> None:
        index_name = f"nipuna-vectors-{org_id}"

        try:
            self.client.create_index(
                name=index_name,
                type="knn_vector",
                dimension=dimension,
            )
        except self.client.exceptions.ResourceAlreadyExistsException:
            pass
        except Exception:
            pass

    async def _get_collection_endpoint(self) -> str:
        try:
            response = self.client.batch_get_collection(
                names=["nipuna-vectors"]
            )
            collections = response.get("collectionDetails", [])
            if collections:
                return collections[0].get("collectionEndpoint", "")
        except Exception:
            pass

        from app.config import get_settings
        settings = get_settings()
        return f"https://{settings.opensearch_endpoint}" if hasattr(settings, "opensearch_endpoint") and settings.opensearch_endpoint else ""


vector_store = VectorStore()
