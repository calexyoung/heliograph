"""Qdrant vector database client with hybrid search support.

This module provides a Qdrant client that supports both dense semantic
vectors and sparse BM25-style vectors for hybrid retrieval.
"""

import uuid
from typing import Any

from services.document_processing.app.config import settings
from services.document_processing.app.core.schemas import ChunkWithEmbedding
from shared.utils.logging import get_logger
from shared.utils.sparse_encoder import SparseEncoder, get_sparse_encoder

logger = get_logger(__name__)


class QdrantClient:
    """Client for Qdrant vector database with hybrid search support.

    Supports both dense semantic vectors and sparse BM25-style vectors
    for improved retrieval accuracy on scientific literature.
    """

    # Named vector identifiers
    DENSE_VECTOR_NAME = "dense"
    SPARSE_VECTOR_NAME = "sparse"

    def __init__(
        self,
        url: str = None,
        api_key: str = None,
        collection_name: str = None,
        sparse_encoder: SparseEncoder | None = None,
        enable_hybrid: bool | None = None,
    ):
        """Initialize Qdrant client.

        Args:
            url: Qdrant server URL
            api_key: API key (optional)
            collection_name: Collection name
            sparse_encoder: Sparse encoder for BM25 vectors
            enable_hybrid: Whether to enable hybrid search (defaults to settings)
        """
        self.url = url or settings.QDRANT_URL
        self.api_key = api_key or settings.QDRANT_API_KEY
        self.collection_name = collection_name or settings.QDRANT_COLLECTION
        self.sparse_encoder = sparse_encoder or get_sparse_encoder()
        self.enable_hybrid = enable_hybrid if enable_hybrid is not None else getattr(
            settings, "ENABLE_HYBRID_SEARCH", True
        )

        self._client = None

    async def _get_client(self):
        """Get or create Qdrant client.

        Returns:
            Qdrant async client
        """
        if self._client is None:
            try:
                from qdrant_client import AsyncQdrantClient
                from qdrant_client.http import models

                self._client = AsyncQdrantClient(
                    url=self.url,
                    api_key=self.api_key,
                )

                # Ensure collection exists
                await self._ensure_collection()

            except ImportError:
                raise RuntimeError(
                    "qdrant-client not installed. "
                    "Install with: pip install qdrant-client"
                )

        return self._client

    async def _ensure_collection(self) -> None:
        """Ensure collection exists with correct schema for hybrid search."""
        from qdrant_client.http import models

        try:
            # Check if collection exists
            collections = await self._client.get_collections()
            collection_names = [c.name for c in collections.collections]

            if self.collection_name not in collection_names:
                logger.info(
                    "creating_qdrant_collection",
                    collection=self.collection_name,
                    dimension=settings.EMBEDDING_DIMENSION,
                    hybrid_enabled=self.enable_hybrid,
                )

                # Configure vectors - use named vectors for hybrid search
                if self.enable_hybrid:
                    vectors_config = {
                        self.DENSE_VECTOR_NAME: models.VectorParams(
                            size=settings.EMBEDDING_DIMENSION,
                            distance=models.Distance.COSINE,
                        ),
                    }
                    sparse_vectors_config = {
                        self.SPARSE_VECTOR_NAME: models.SparseVectorParams(
                            modifier=models.Modifier.IDF,  # Apply IDF weighting
                        ),
                    }
                else:
                    vectors_config = models.VectorParams(
                        size=settings.EMBEDDING_DIMENSION,
                        distance=models.Distance.COSINE,
                    )
                    sparse_vectors_config = None

                await self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=vectors_config,
                    sparse_vectors_config=sparse_vectors_config,
                )

                # Create payload indexes for filtering
                await self._client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="document_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
                await self._client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="section",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
                await self._client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="year",
                    field_schema=models.PayloadSchemaType.INTEGER,
                )

                logger.info(
                    "qdrant_collection_created",
                    collection=self.collection_name,
                    hybrid_enabled=self.enable_hybrid,
                )

        except Exception as e:
            logger.error("qdrant_collection_error", error=str(e))
            raise

    async def upsert_chunks(
        self,
        chunks: list[ChunkWithEmbedding],
        document_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Upsert chunks into Qdrant with both dense and sparse vectors.

        Args:
            chunks: Chunks with embeddings
            document_metadata: Additional document metadata
        """
        if not chunks:
            return

        from qdrant_client.http import models

        client = await self._get_client()

        # Prepare points
        points = []
        for chunk in chunks:
            payload = {
                "document_id": str(chunk.document_id),
                "chunk_id": str(chunk.chunk_id),
                "sequence_number": chunk.sequence_number,
                "section": chunk.section.value if chunk.section else None,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "char_offset_start": chunk.char_offset_start,
                "char_offset_end": chunk.char_offset_end,
                "token_count": chunk.token_count,
                "text_preview": chunk.text[:500],  # Store preview for debugging
                "text": chunk.text,  # Store full text for sparse encoding at search time
            }

            # Add document metadata
            if document_metadata:
                payload.update({
                    "doi": document_metadata.get("doi"),
                    "title": document_metadata.get("title"),
                    "year": document_metadata.get("year"),
                    "authors": document_metadata.get("authors"),
                    "journal": document_metadata.get("journal"),
                })

            # Add chunk metadata
            payload.update(chunk.metadata)

            # Build vector configuration
            if self.enable_hybrid:
                # Generate sparse vector for BM25-style search
                sparse_data = self.sparse_encoder.encode(chunk.text)

                vector = {
                    self.DENSE_VECTOR_NAME: chunk.embedding,
                }

                # Only add sparse vector if we have terms
                sparse_vector = None
                if sparse_data["indices"]:
                    sparse_vector = {
                        self.SPARSE_VECTOR_NAME: models.SparseVector(
                            indices=sparse_data["indices"],
                            values=sparse_data["values"],
                        )
                    }

                points.append(
                    models.PointStruct(
                        id=str(chunk.chunk_id),
                        vector=vector,
                        payload=payload,
                    )
                )

                # Update sparse vectors separately if present
                if sparse_vector:
                    points[-1].vector.update(sparse_vector)
            else:
                points.append(
                    models.PointStruct(
                        id=str(chunk.chunk_id),
                        vector=chunk.embedding,
                        payload=payload,
                    )
                )

        # Upsert in batches
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]

            await client.upsert(
                collection_name=self.collection_name,
                points=batch,
            )

        logger.info(
            "chunks_upserted_to_qdrant",
            count=len(chunks),
            collection=self.collection_name,
            hybrid_enabled=self.enable_hybrid,
        )

    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar chunks.

        Args:
            query_vector: Query embedding
            limit: Maximum results
            filters: Filter conditions
            score_threshold: Minimum similarity score

        Returns:
            List of matching chunks with scores
        """
        from qdrant_client.http import models

        client = await self._get_client()

        # Build filter
        qdrant_filter = None
        if filters:
            conditions = []

            if "document_id" in filters:
                conditions.append(
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=str(filters["document_id"])),
                    )
                )

            if "document_ids" in filters:
                conditions.append(
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchAny(any=[str(d) for d in filters["document_ids"]]),
                    )
                )

            if "section" in filters:
                conditions.append(
                    models.FieldCondition(
                        key="section",
                        match=models.MatchValue(value=filters["section"]),
                    )
                )

            if "year_from" in filters:
                conditions.append(
                    models.FieldCondition(
                        key="year",
                        range=models.Range(gte=filters["year_from"]),
                    )
                )

            if "year_to" in filters:
                conditions.append(
                    models.FieldCondition(
                        key="year",
                        range=models.Range(lte=filters["year_to"]),
                    )
                )

            if conditions:
                qdrant_filter = models.Filter(must=conditions)

        # Execute search
        results = await client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit,
            query_filter=qdrant_filter,
            score_threshold=score_threshold,
            with_payload=True,
        )

        # Format results
        return [
            {
                "chunk_id": result.id,
                "score": result.score,
                "payload": result.payload,
            }
            for result in results
        ]

    async def hybrid_search(
        self,
        query_text: str,
        query_vector: list[float],
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        score_threshold: float | None = None,
        dense_weight: float = 0.7,
        sparse_weight: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Hybrid search combining dense vectors and sparse BM25.

        Uses Reciprocal Rank Fusion (RRF) to combine results from
        dense semantic search and sparse keyword search.

        Args:
            query_text: Original query text for sparse encoding
            query_vector: Dense query embedding
            limit: Maximum results
            filters: Filter conditions
            score_threshold: Minimum similarity score
            dense_weight: Weight for dense vector results (0-1)
            sparse_weight: Weight for sparse vector results (0-1)

        Returns:
            List of matching chunks with fused scores
        """
        from qdrant_client.http import models

        client = await self._get_client()

        # Build filter
        qdrant_filter = None
        if filters:
            conditions = []

            if "document_id" in filters:
                conditions.append(
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=str(filters["document_id"])),
                    )
                )

            if "document_ids" in filters:
                conditions.append(
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchAny(any=[str(d) for d in filters["document_ids"]]),
                    )
                )

            if "section" in filters:
                conditions.append(
                    models.FieldCondition(
                        key="section",
                        match=models.MatchValue(value=filters["section"]),
                    )
                )

            if "year_from" in filters:
                conditions.append(
                    models.FieldCondition(
                        key="year",
                        range=models.Range(gte=filters["year_from"]),
                    )
                )

            if "year_to" in filters:
                conditions.append(
                    models.FieldCondition(
                        key="year",
                        range=models.Range(lte=filters["year_to"]),
                    )
                )

            if conditions:
                qdrant_filter = models.Filter(must=conditions)

        # Generate sparse query vector
        sparse_query = self.sparse_encoder.encode_query(query_text)

        # If no sparse terms match, fall back to dense-only search
        if not sparse_query["indices"]:
            logger.debug("hybrid_search_fallback_to_dense", reason="no_sparse_terms")
            return await self.search(
                query_vector=query_vector,
                limit=limit,
                filters=filters,
                score_threshold=score_threshold,
            )

        # Use Qdrant's query API with prefetch for hybrid search
        # This fetches from both dense and sparse, then fuses results
        try:
            results = await client.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    # Dense vector search
                    models.Prefetch(
                        query=query_vector,
                        using=self.DENSE_VECTOR_NAME,
                        limit=limit * 2,  # Fetch more for fusion
                        filter=qdrant_filter,
                    ),
                    # Sparse vector search
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=sparse_query["indices"],
                            values=sparse_query["values"],
                        ),
                        using=self.SPARSE_VECTOR_NAME,
                        limit=limit * 2,
                        filter=qdrant_filter,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),  # Reciprocal Rank Fusion
                limit=limit,
                with_payload=True,
                score_threshold=score_threshold,
            )

            logger.debug(
                "hybrid_search_completed",
                results_count=len(results.points),
                dense_weight=dense_weight,
                sparse_weight=sparse_weight,
            )

            # Format results
            return [
                {
                    "chunk_id": result.id,
                    "score": result.score,
                    "payload": result.payload,
                }
                for result in results.points
            ]

        except Exception as e:
            # Fall back to dense-only search if hybrid fails
            logger.warning(
                "hybrid_search_fallback",
                error=str(e),
                reason="query_api_error",
            )
            return await self.search(
                query_vector=query_vector,
                limit=limit,
                filters=filters,
                score_threshold=score_threshold,
            )

    async def delete_by_document(self, document_id: uuid.UUID) -> None:
        """Delete all chunks for a document.

        Args:
            document_id: Document ID
        """
        from qdrant_client.http import models

        client = await self._get_client()

        await client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=str(document_id)),
                        )
                    ]
                )
            ),
        )

        logger.info(
            "document_chunks_deleted_from_qdrant",
            document_id=str(document_id),
        )

    async def get_collection_info(self) -> dict[str, Any]:
        """Get collection information.

        Returns:
            Collection info
        """
        client = await self._get_client()

        info = await client.get_collection(self.collection_name)

        return {
            "name": info.config.params.collection_name if hasattr(info.config.params, 'collection_name') else self.collection_name,
            "vectors_count": info.vectors_count,
            "points_count": info.points_count,
            "status": info.status.name if info.status else "unknown",
        }

    async def check_health(self) -> bool:
        """Check Qdrant health.

        Returns:
            True if healthy
        """
        try:
            client = await self._get_client()
            await client.get_collections()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close client connection."""
        if self._client:
            await self._client.close()
            self._client = None
