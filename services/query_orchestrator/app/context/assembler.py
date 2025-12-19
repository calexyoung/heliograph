"""Context assembly for LLM generation."""

from typing import Any
from uuid import UUID

import structlog
import tiktoken

from ..config import Settings
from ..core.schemas import ChunkEvidence, Citation, EvidenceMap, GraphPath

logger = structlog.get_logger()


class ContextAssembler:
    """Assembles context for LLM generation from retrieval results."""

    def __init__(self, settings: Settings):
        """Initialize the context assembler."""
        self.settings = settings
        try:
            self._tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._tokenizer = None

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        if self._tokenizer:
            return len(self._tokenizer.encode(text))
        # Fallback: approximate 4 chars per token
        return len(text) // 4

    def assemble_context(
        self,
        chunks: list[ChunkEvidence],
        graph_paths: list[GraphPath],
        max_tokens: int | None = None,
    ) -> tuple[str, list[Citation]]:
        """Assemble context from chunks and graph paths.

        Args:
            chunks: List of relevant chunks
            graph_paths: Graph paths providing context
            max_tokens: Maximum tokens for context

        Returns:
            Tuple of (context string, citations)
        """
        max_tokens = max_tokens or self.settings.MAX_CONTEXT_TOKENS
        current_tokens = 0
        context_parts = []
        citations = []

        # Add chunks to context
        for i, chunk in enumerate(chunks[: self.settings.MAX_CHUNKS_IN_CONTEXT]):
            chunk_text = self._format_chunk(chunk, i + 1)
            chunk_tokens = self.count_tokens(chunk_text)

            if current_tokens + chunk_tokens > max_tokens:
                break

            context_parts.append(chunk_text)
            current_tokens += chunk_tokens

            # Create citation
            citation = Citation(
                citation_id=i + 1,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                title=chunk.metadata.get("title") or "Unknown",
                authors=chunk.metadata.get("authors") or [],
                year=chunk.metadata.get("year"),
                page=chunk.page_start,
                section=chunk.section,
                snippet=chunk.text[:200] + "..." if len(chunk.text) > 200 else chunk.text,
            )
            citations.append(citation)

        # Add graph context if space allows
        if graph_paths and current_tokens < max_tokens - 200:
            graph_context = self._format_graph_context(graph_paths)
            graph_tokens = self.count_tokens(graph_context)

            if current_tokens + graph_tokens <= max_tokens:
                context_parts.append(graph_context)

        context = "\n\n".join(context_parts)
        return context, citations

    def _format_chunk(self, chunk: ChunkEvidence, citation_id: int) -> str:
        """Format a chunk for the context."""
        parts = [f"[{citation_id}]"]

        if self.settings.INCLUDE_METADATA:
            metadata_parts = []
            if chunk.metadata.get("title"):
                metadata_parts.append(f"Source: {chunk.metadata['title']}")
            if chunk.metadata.get("year"):
                metadata_parts.append(f"({chunk.metadata['year']})")
            if chunk.section:
                metadata_parts.append(f"Section: {chunk.section}")

            if metadata_parts:
                parts.append(" ".join(metadata_parts))

        parts.append(chunk.text)

        return "\n".join(parts)

    def _format_graph_context(self, graph_paths: list[GraphPath]) -> str:
        """Format graph paths as additional context."""
        if not graph_paths:
            return ""

        lines = ["Related concepts from knowledge graph:"]

        for path in graph_paths[:5]:  # Limit number of paths
            if len(path.nodes) >= 2:
                path_str = " -> ".join(path.nodes)
                lines.append(f"- {path_str}")

        return "\n".join(lines)

    def select_diverse_chunks(
        self,
        chunks: list[ChunkEvidence],
        max_chunks: int | None = None,
    ) -> list[ChunkEvidence]:
        """Select diverse chunks covering different documents/sections.

        Args:
            chunks: All candidate chunks
            max_chunks: Maximum number of chunks to select

        Returns:
            Selected diverse chunks
        """
        max_chunks = max_chunks or self.settings.MAX_CHUNKS_IN_CONTEXT

        if len(chunks) <= max_chunks:
            return chunks

        selected = []
        seen_docs: set[UUID] = set()
        seen_sections: set[tuple[UUID, str | None]] = set()

        # First pass: one chunk per document
        for chunk in chunks:
            if chunk.document_id not in seen_docs:
                selected.append(chunk)
                seen_docs.add(chunk.document_id)
                seen_sections.add((chunk.document_id, chunk.section))

                if len(selected) >= max_chunks:
                    break

        # Second pass: fill remaining with best scores
        if len(selected) < max_chunks:
            for chunk in chunks:
                if chunk not in selected:
                    # Prefer chunks from different sections
                    key = (chunk.document_id, chunk.section)
                    if key not in seen_sections:
                        selected.append(chunk)
                        seen_sections.add(key)

                        if len(selected) >= max_chunks:
                            break

        # Third pass: fill any remaining slots
        if len(selected) < max_chunks:
            for chunk in chunks:
                if chunk not in selected:
                    selected.append(chunk)
                    if len(selected) >= max_chunks:
                        break

        return selected


class EvidenceTracker:
    """Tracks evidence used in responses."""

    def __init__(self):
        """Initialize the evidence tracker."""
        self.evidence_map: dict[int, ChunkEvidence] = {}
        self.graph_paths: list[GraphPath] = []

    def add_chunk(self, citation_id: int, chunk: ChunkEvidence) -> None:
        """Add a chunk to the evidence map."""
        self.evidence_map[citation_id] = chunk

    def add_graph_paths(self, paths: list[GraphPath]) -> None:
        """Add graph paths to evidence."""
        self.graph_paths.extend(paths)

    def get_evidence_for_citation(self, citation_id: int) -> ChunkEvidence | None:
        """Get the chunk evidence for a citation."""
        return self.evidence_map.get(citation_id)

    def to_evidence_map(self) -> EvidenceMap:
        """Convert to EvidenceMap schema."""
        return EvidenceMap(
            chunks=list(self.evidence_map.values()),
            graph_paths=self.graph_paths,
            total_chunks_retrieved=len(self.evidence_map),
            total_chunks_after_rerank=len(self.evidence_map),
        )
