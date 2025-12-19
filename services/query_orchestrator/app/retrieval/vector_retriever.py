"""Vector retrieval using Qdrant with hybrid search support."""

from typing import Any
from uuid import UUID

import httpx
import structlog

from ..config import Settings
from ..core.schemas import ChunkEvidence, SearchFilters
from shared.utils.sparse_encoder import SparseEncoder, get_sparse_encoder

logger = structlog.get_logger()


class VectorRetriever:
    """Retrieves relevant chunks using vector similarity search.

    Supports both dense-only and hybrid (dense + sparse) search modes.
    Hybrid search combines semantic similarity with BM25-style keyword matching.
    """

    # Named vector identifiers (must match QdrantClient)
    DENSE_VECTOR_NAME = "dense"
    SPARSE_VECTOR_NAME = "sparse"

    def __init__(self, settings: Settings):
        """Initialize the vector retriever."""
        self.settings = settings
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self._embedder = None
        self.sparse_encoder = get_sparse_encoder()
        self.enable_hybrid = getattr(settings, "ENABLE_HYBRID_SEARCH", True)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.http_client.aclose()

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        filters: SearchFilters | None = None,
        use_hybrid: bool | None = None,
    ) -> list[ChunkEvidence]:
        """Search for relevant chunks using hybrid or dense-only search.

        Args:
            query: The search query
            top_k: Number of results to return
            filters: Optional filters to apply
            use_hybrid: Override hybrid search setting (None uses default)

        Returns:
            List of chunk evidence sorted by relevance
        """
        top_k = top_k or self.settings.VECTOR_TOP_K
        use_hybrid = use_hybrid if use_hybrid is not None else self.enable_hybrid

        # Generate query embedding
        query_embedding = await self._get_embedding(query)

        # Build Qdrant filter
        qdrant_filter = self._build_filter(filters) if filters else None

        # Try hybrid search if enabled
        if use_hybrid:
            try:
                results = await self._hybrid_search(
                    query=query,
                    query_embedding=query_embedding,
                    top_k=top_k,
                    qdrant_filter=qdrant_filter,
                )
                if results:
                    return results
                logger.debug("hybrid_search_empty_falling_back_to_dense")
            except Exception as e:
                logger.warning("hybrid_search_failed_falling_back", error=str(e))

        # Fall back to dense-only search
        return await self._dense_search(
            query_embedding=query_embedding,
            top_k=top_k,
            qdrant_filter=qdrant_filter,
        )

    async def _dense_search(
        self,
        query_embedding: list[float],
        top_k: int,
        qdrant_filter: dict[str, Any] | None,
    ) -> list[ChunkEvidence]:
        """Perform dense-only vector search."""
        try:
            response = await self.http_client.post(
                f"{self.settings.QDRANT_URL}/collections/{self.settings.QDRANT_COLLECTION}/points/search",
                json={
                    "vector": {
                        "name": self.DENSE_VECTOR_NAME,
                        "vector": query_embedding,
                    },
                    "limit": top_k,
                    "with_payload": True,
                    "filter": qdrant_filter,
                    "score_threshold": self.settings.MIN_SIMILARITY_SCORE,
                },
            )
            response.raise_for_status()
            results = response.json()

        except Exception as e:
            # Try without named vectors (backward compatibility)
            logger.debug("trying_legacy_search_format")
            try:
                response = await self.http_client.post(
                    f"{self.settings.QDRANT_URL}/collections/{self.settings.QDRANT_COLLECTION}/points/search",
                    json={
                        "vector": query_embedding,
                        "limit": top_k,
                        "with_payload": True,
                        "filter": qdrant_filter,
                        "score_threshold": self.settings.MIN_SIMILARITY_SCORE,
                    },
                )
                response.raise_for_status()
                results = response.json()
            except Exception as e2:
                logger.error("Qdrant search failed", error=str(e2))
                return []

        return self._parse_results(results.get("result", []))

    async def _hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int,
        qdrant_filter: dict[str, Any] | None,
    ) -> list[ChunkEvidence]:
        """Perform hybrid search combining dense and sparse vectors."""
        # Generate sparse query vector
        sparse_query = self.sparse_encoder.encode_query(query)

        if not sparse_query["indices"]:
            logger.debug("no_sparse_terms_for_query", query=query[:50])
            return []

        # Use Qdrant's query API with prefetch for hybrid search
        response = await self.http_client.post(
            f"{self.settings.QDRANT_URL}/collections/{self.settings.QDRANT_COLLECTION}/points/query",
            json={
                "prefetch": [
                    {
                        "query": {
                            "name": self.DENSE_VECTOR_NAME,
                            "vector": query_embedding,
                        },
                        "limit": top_k * 2,
                        "filter": qdrant_filter,
                    },
                    {
                        "query": {
                            "name": self.SPARSE_VECTOR_NAME,
                            "indices": sparse_query["indices"],
                            "values": sparse_query["values"],
                        },
                        "limit": top_k * 2,
                        "filter": qdrant_filter,
                    },
                ],
                "query": {"fusion": "rrf"},  # Reciprocal Rank Fusion
                "limit": top_k,
                "with_payload": True,
                "score_threshold": self.settings.MIN_SIMILARITY_SCORE,
            },
        )
        response.raise_for_status()
        results = response.json()

        logger.info(
            "hybrid_search_completed",
            query_preview=query[:50],
            results_count=len(results.get("points", [])),
        )

        return self._parse_results(results.get("points", []))

    def _parse_results(self, hits: list[dict[str, Any]]) -> list[ChunkEvidence]:
        """Parse Qdrant search results into ChunkEvidence objects."""
        chunks = []
        for hit in hits:
            payload = hit.get("payload", {})
            try:
                chunk = ChunkEvidence(
                    chunk_id=UUID(payload.get("chunk_id", str(hit.get("id")))),
                    document_id=UUID(payload.get("document_id")),
                    text=payload.get("text", payload.get("text_preview", "")),
                    section=payload.get("section"),
                    page_start=payload.get("page_start"),
                    page_end=payload.get("page_end"),
                    similarity_score=hit.get("score", 0.0),
                    metadata={
                        "title": payload.get("title"),
                        "authors": payload.get("authors", []),
                        "year": payload.get("year"),
                        "journal": payload.get("journal"),
                    },
                )
                chunks.append(chunk)
            except Exception as e:
                logger.warning("failed_to_parse_chunk", error=str(e), hit_id=hit.get("id"))

        return chunks

    async def search_by_document(
        self,
        query: str,
        document_ids: list[UUID],
        top_k: int | None = None,
    ) -> list[ChunkEvidence]:
        """Search within specific documents.

        Args:
            query: The search query
            document_ids: List of document IDs to search within
            top_k: Number of results to return

        Returns:
            List of chunk evidence
        """
        filters = SearchFilters(document_ids=[str(d) for d in document_ids])
        return await self.search(query, top_k, filters)

    async def _get_embedding(self, text: str) -> list[float]:
        """Generate embedding for text."""
        if self.settings.EMBEDDING_PROVIDER == "openai":
            return await self._get_openai_embedding(text)
        else:
            return await self._get_local_embedding(text)

    async def _get_openai_embedding(self, text: str) -> list[float]:
        """Generate embedding using OpenAI."""
        if not self.settings.OPENAI_API_KEY:
            raise ValueError("OpenAI API key not configured")

        response = await self.http_client.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {self.settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "input": text,
                "model": "text-embedding-3-small",
            },
        )
        response.raise_for_status()
        result = response.json()
        return result["data"][0]["embedding"]

    async def _get_local_embedding(self, text: str) -> list[float]:
        """Generate embedding using local model."""
        # Lazy load sentence transformers
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._embedder = SentenceTransformer(self.settings.EMBEDDING_MODEL)
            except ImportError:
                logger.error("sentence-transformers not installed")
                # Return zero vector as fallback
                return [0.0] * self.settings.EMBEDDING_DIMENSION

        embedding = self._embedder.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def _build_filter(self, filters: SearchFilters) -> dict[str, Any]:
        """Build Qdrant filter from SearchFilters."""
        must_conditions = []

        if filters.document_ids:
            must_conditions.append({
                "key": "document_id",
                "match": {"any": filters.document_ids},
            })

        if filters.year_min is not None or filters.year_max is not None:
            range_filter: dict[str, Any] = {"key": "year", "range": {}}
            if filters.year_min is not None:
                range_filter["range"]["gte"] = filters.year_min
            if filters.year_max is not None:
                range_filter["range"]["lte"] = filters.year_max
            must_conditions.append(range_filter)

        if filters.sections:
            must_conditions.append({
                "key": "section",
                "match": {"any": filters.sections},
            })

        if not must_conditions:
            return {}

        return {"must": must_conditions}
