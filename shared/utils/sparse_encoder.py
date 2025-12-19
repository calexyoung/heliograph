"""Sparse vector encoder for BM25-style keyword search.

This module provides sparse vector encoding for hybrid retrieval,
combining dense semantic vectors with sparse keyword-based vectors.
"""

import math
import re
from collections import Counter
from typing import Any

from shared.utils.logging import get_logger

logger = get_logger(__name__)


class SparseEncoder:
    """Encodes text into sparse vectors using BM25-inspired term weighting.

    This encoder creates sparse vectors suitable for keyword-based retrieval
    in Qdrant's hybrid search. It uses a simplified BM25 approach with
    term frequency and inverse document frequency weighting.
    """

    # Scientific domain stopwords (common but not useful for retrieval)
    STOPWORDS = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
        "be", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "must", "shall", "can", "need",
        "this", "that", "these", "those", "it", "its", "they", "them", "their",
        "we", "us", "our", "you", "your", "he", "she", "his", "her", "i", "me",
        "my", "who", "which", "what", "where", "when", "why", "how",
        "all", "each", "every", "both", "few", "more", "most", "other", "some",
        "such", "no", "not", "only", "same", "so", "than", "too", "very",
        "just", "also", "now", "here", "there", "then", "if", "because",
        "about", "into", "through", "during", "before", "after", "above",
        "below", "between", "under", "again", "further", "once", "et", "al",
        "fig", "figure", "table", "section", "eq", "equation", "ref",
    }

    # BM25 parameters
    K1 = 1.5  # Term frequency saturation
    B = 0.75  # Length normalization

    def __init__(
        self,
        vocab: dict[str, int] | None = None,
        idf_scores: dict[str, float] | None = None,
        avg_doc_length: float = 200.0,
    ):
        """Initialize the sparse encoder.

        Args:
            vocab: Mapping from terms to indices (built from corpus)
            idf_scores: Pre-computed IDF scores for terms
            avg_doc_length: Average document length in tokens
        """
        self.vocab = vocab or {}
        self.idf_scores = idf_scores or {}
        self.avg_doc_length = avg_doc_length
        self._next_idx = max(self.vocab.values()) + 1 if self.vocab else 0

    def tokenize(self, text: str) -> list[str]:
        """Tokenize text into terms.

        Args:
            text: Input text

        Returns:
            List of normalized tokens
        """
        # Lowercase and extract words
        text = text.lower()
        # Keep alphanumeric and hyphens for compound terms
        tokens = re.findall(r"[a-z0-9]+-?[a-z0-9]*", text)
        # Filter stopwords and short tokens
        tokens = [t for t in tokens if t not in self.STOPWORDS and len(t) > 2]
        return tokens

    def encode(self, text: str) -> dict[str, Any]:
        """Encode text into a sparse vector.

        Args:
            text: Input text to encode

        Returns:
            Dictionary with 'indices' and 'values' for Qdrant sparse vector
        """
        tokens = self.tokenize(text)

        if not tokens:
            return {"indices": [], "values": []}

        # Count term frequencies
        term_counts = Counter(tokens)
        doc_length = len(tokens)

        indices = []
        values = []

        for term, tf in term_counts.items():
            # Get or create term index
            if term not in self.vocab:
                self.vocab[term] = self._next_idx
                self._next_idx += 1

            idx = self.vocab[term]

            # Get IDF (default to 1.0 for unknown terms)
            idf = self.idf_scores.get(term, 1.0)

            # BM25 term weight
            tf_component = (tf * (self.K1 + 1)) / (
                tf + self.K1 * (1 - self.B + self.B * doc_length / self.avg_doc_length)
            )
            weight = idf * tf_component

            indices.append(idx)
            values.append(float(weight))

        return {"indices": indices, "values": values}

    def encode_query(self, query: str) -> dict[str, Any]:
        """Encode a query into a sparse vector.

        For queries, we use simpler term frequency weighting
        since queries are typically short.

        Args:
            query: Query text

        Returns:
            Dictionary with 'indices' and 'values' for Qdrant sparse vector
        """
        tokens = self.tokenize(query)

        if not tokens:
            return {"indices": [], "values": []}

        term_counts = Counter(tokens)

        indices = []
        values = []

        for term, tf in term_counts.items():
            # Only use terms we've seen in documents
            if term not in self.vocab:
                continue

            idx = self.vocab[term]
            idf = self.idf_scores.get(term, 1.0)

            # Query weighting: IDF * (k1 + 1) * tf / (k1 + tf)
            weight = idf * (self.K1 + 1) * tf / (self.K1 + tf)

            indices.append(idx)
            values.append(float(weight))

        return {"indices": indices, "values": values}

    def build_idf(self, documents: list[str]) -> None:
        """Build IDF scores from a corpus of documents.

        Args:
            documents: List of document texts
        """
        doc_count = len(documents)
        doc_freq: dict[str, int] = Counter()

        for doc in documents:
            tokens = set(self.tokenize(doc))
            for token in tokens:
                doc_freq[token] += 1

        # Compute IDF scores
        self.idf_scores = {}
        for term, df in doc_freq.items():
            # BM25 IDF formula
            self.idf_scores[term] = math.log((doc_count - df + 0.5) / (df + 0.5) + 1)

        # Compute average document length
        total_length = sum(len(self.tokenize(doc)) for doc in documents)
        self.avg_doc_length = total_length / doc_count if doc_count > 0 else 200.0

        logger.info(
            "sparse_encoder_idf_built",
            vocab_size=len(self.vocab),
            doc_count=doc_count,
            avg_doc_length=self.avg_doc_length,
        )

    def to_dict(self) -> dict[str, Any]:
        """Export encoder state for persistence.

        Returns:
            Dictionary containing encoder state
        """
        return {
            "vocab": self.vocab,
            "idf_scores": self.idf_scores,
            "avg_doc_length": self.avg_doc_length,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SparseEncoder":
        """Create encoder from persisted state.

        Args:
            data: Dictionary from to_dict()

        Returns:
            SparseEncoder instance
        """
        return cls(
            vocab=data.get("vocab", {}),
            idf_scores=data.get("idf_scores", {}),
            avg_doc_length=data.get("avg_doc_length", 200.0),
        )


# Global encoder instance for sharing across requests
_global_encoder: SparseEncoder | None = None


def get_sparse_encoder() -> SparseEncoder:
    """Get the global sparse encoder instance.

    Returns:
        SparseEncoder instance
    """
    global _global_encoder
    if _global_encoder is None:
        _global_encoder = SparseEncoder()
    return _global_encoder


def set_sparse_encoder(encoder: SparseEncoder) -> None:
    """Set the global sparse encoder instance.

    Args:
        encoder: SparseEncoder instance to use globally
    """
    global _global_encoder
    _global_encoder = encoder
