"""Re-ranking module for improving retrieval results."""

from typing import Any

import structlog

from ..config import Settings
from ..core.schemas import ChunkEvidence

logger = structlog.get_logger()


class Reranker:
    """Re-ranks retrieval results using cross-encoder models."""

    def __init__(self, settings: Settings):
        """Initialize the reranker."""
        self.settings = settings
        self._model = None

    def _load_model(self) -> Any:
        """Lazy load the cross-encoder model."""
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(self.settings.RERANK_MODEL)
                logger.info("Loaded reranker model", model=self.settings.RERANK_MODEL)
            except ImportError:
                logger.warning("sentence-transformers not available, reranking disabled")
                return None
        return self._model

    def rerank(
        self,
        query: str,
        chunks: list[ChunkEvidence],
        top_k: int | None = None,
    ) -> list[ChunkEvidence]:
        """Re-rank chunks based on query relevance.

        Args:
            query: The search query
            chunks: List of chunks to rerank
            top_k: Number of top results to return

        Returns:
            Re-ranked list of chunks
        """
        if not self.settings.RERANK_ENABLED:
            return chunks[:top_k] if top_k else chunks

        if not chunks:
            return chunks

        top_k = top_k or self.settings.RERANK_TOP_K

        model = self._load_model()
        if model is None:
            # Fall back to original ranking
            return chunks[:top_k]

        try:
            # Prepare query-document pairs
            pairs = [(query, chunk.text) for chunk in chunks]

            # Get scores from cross-encoder
            scores = model.predict(pairs)

            # Update chunks with rerank scores
            for chunk, score in zip(chunks, scores):
                chunk.rerank_score = float(score)

            # Sort by rerank score
            reranked = sorted(chunks, key=lambda c: c.rerank_score or 0.0, reverse=True)

            return reranked[:top_k]

        except Exception as e:
            logger.error("Reranking failed", error=str(e))
            return chunks[:top_k]


class MMRReranker:
    """Maximal Marginal Relevance for diversity in results."""

    def __init__(self, lambda_param: float = 0.7):
        """Initialize MMR reranker.

        Args:
            lambda_param: Balance between relevance (1.0) and diversity (0.0)
        """
        self.lambda_param = lambda_param
        self._embedder = None

    def _load_embedder(self) -> Any:
        """Lazy load embedding model."""
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError:
                return None
        return self._embedder

    def rerank_mmr(
        self,
        query: str,
        chunks: list[ChunkEvidence],
        top_k: int = 10,
    ) -> list[ChunkEvidence]:
        """Re-rank using MMR for diversity.

        Args:
            query: The search query
            chunks: List of chunks to rerank
            top_k: Number of results to return

        Returns:
            MMR-reranked list of chunks
        """
        if not chunks or len(chunks) <= top_k:
            return chunks

        embedder = self._load_embedder()
        if embedder is None:
            return chunks[:top_k]

        try:
            import numpy as np

            # Get embeddings
            query_embedding = embedder.encode(query)
            chunk_embeddings = embedder.encode([c.text for c in chunks])

            # Calculate relevance scores (cosine similarity to query)
            relevance_scores = np.dot(chunk_embeddings, query_embedding) / (
                np.linalg.norm(chunk_embeddings, axis=1) * np.linalg.norm(query_embedding)
            )

            # MMR selection
            selected_indices: list[int] = []
            remaining_indices = list(range(len(chunks)))

            while len(selected_indices) < top_k and remaining_indices:
                mmr_scores = []

                for idx in remaining_indices:
                    # Relevance term
                    relevance = relevance_scores[idx]

                    # Diversity term (max similarity to already selected)
                    if selected_indices:
                        similarities = [
                            np.dot(chunk_embeddings[idx], chunk_embeddings[sel_idx])
                            / (
                                np.linalg.norm(chunk_embeddings[idx])
                                * np.linalg.norm(chunk_embeddings[sel_idx])
                            )
                            for sel_idx in selected_indices
                        ]
                        max_similarity = max(similarities)
                    else:
                        max_similarity = 0.0

                    # MMR score
                    mmr = self.lambda_param * relevance - (1 - self.lambda_param) * max_similarity
                    mmr_scores.append((idx, mmr))

                # Select best MMR score
                best_idx = max(mmr_scores, key=lambda x: x[1])[0]
                selected_indices.append(best_idx)
                remaining_indices.remove(best_idx)

            # Return selected chunks in order
            return [chunks[i] for i in selected_indices]

        except Exception as e:
            logger.error("MMR reranking failed", error=str(e))
            return chunks[:top_k]
