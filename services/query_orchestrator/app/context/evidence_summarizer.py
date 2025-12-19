"""Evidence summarizer for extracting query-relevant information from chunks.

Inspired by paper-qa's evidence gathering approach, this module summarizes
each retrieved chunk to extract only the information relevant to the query,
improving answer quality and reducing noise in the context.
"""

import asyncio
from typing import Any

import httpx
import structlog

from ..config import Settings
from ..core.schemas import ChunkEvidence

logger = structlog.get_logger()


SUMMARIZATION_PROMPT = """You are extracting relevant information from a scientific document chunk.

Query: {query}

Document chunk:
{chunk_text}

Extract and summarize ONLY the information from this chunk that is directly relevant to answering the query.
If the chunk contains no relevant information, respond with "NO_RELEVANT_INFO".

Be concise but preserve important details, numbers, and findings. Keep your summary under 150 words.

Relevant information:"""


class EvidenceSummarizer:
    """Summarizes retrieved evidence to extract query-relevant information.

    This improves RAG quality by:
    1. Reducing noise in the context
    2. Focusing on query-relevant details
    3. Filtering out irrelevant chunks early
    """

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ):
        """Initialize the evidence summarizer.

        Args:
            settings: Service settings
            http_client: Optional HTTP client for LLM requests
        """
        self.settings = settings
        self.http_client = http_client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = http_client is None

    async def close(self) -> None:
        """Close resources."""
        if self._owns_client:
            await self.http_client.aclose()

    async def summarize_evidence(
        self,
        query: str,
        chunks: list[ChunkEvidence],
        max_concurrent: int = 5,
    ) -> list[ChunkEvidence]:
        """Summarize each chunk to extract query-relevant information.

        Args:
            query: The user's query
            chunks: Retrieved chunks to summarize
            max_concurrent: Maximum concurrent summarization requests

        Returns:
            List of chunks with summarized text (filtered to relevant ones)
        """
        if not chunks:
            return []

        # Check if summarization is enabled
        if not getattr(self.settings, "ENABLE_EVIDENCE_SUMMARIZATION", True):
            logger.debug("evidence_summarization_disabled")
            return chunks

        logger.info(
            "summarizing_evidence",
            chunk_count=len(chunks),
            query_preview=query[:50],
        )

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(max_concurrent)

        async def summarize_one(chunk: ChunkEvidence) -> ChunkEvidence | None:
            async with semaphore:
                return await self._summarize_chunk(query, chunk)

        # Summarize all chunks concurrently
        tasks = [summarize_one(chunk) for chunk in chunks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter results, keeping only successful summarizations with relevant info
        summarized_chunks = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    "chunk_summarization_failed",
                    chunk_id=str(chunks[i].chunk_id),
                    error=str(result),
                )
                # Keep original chunk on error
                summarized_chunks.append(chunks[i])
            elif result is not None:
                summarized_chunks.append(result)
            # result is None means chunk was filtered as irrelevant

        logger.info(
            "evidence_summarization_complete",
            original_count=len(chunks),
            summarized_count=len(summarized_chunks),
            filtered_count=len(chunks) - len(summarized_chunks),
        )

        return summarized_chunks

    async def _summarize_chunk(
        self,
        query: str,
        chunk: ChunkEvidence,
    ) -> ChunkEvidence | None:
        """Summarize a single chunk.

        Args:
            query: The user's query
            chunk: Chunk to summarize

        Returns:
            Chunk with summarized text, or None if no relevant info
        """
        prompt = SUMMARIZATION_PROMPT.format(
            query=query,
            chunk_text=chunk.text[:2000],  # Limit chunk size
        )

        try:
            # Call LLM service for summarization
            response = await self.http_client.post(
                f"{self.settings.LLM_SERVICE_URL}/api/v1/generate",
                json={
                    "query": prompt,
                    "context": "",
                    "citations": [],
                    "intent": "SUMMARIZE",
                    "max_tokens": 200,
                },
                timeout=15.0,
            )
            response.raise_for_status()
            result = response.json()
            summary = result.get("answer", "").strip()

            # Check if chunk was marked as irrelevant
            if not summary or "NO_RELEVANT_INFO" in summary.upper():
                logger.debug(
                    "chunk_filtered_no_relevant_info",
                    chunk_id=str(chunk.chunk_id),
                )
                return None

            # Create new chunk with summarized text
            return ChunkEvidence(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                text=summary,
                section=chunk.section,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                similarity_score=chunk.similarity_score,
                metadata={
                    **chunk.metadata,
                    "original_text": chunk.text[:500],  # Keep preview of original
                    "summarized": True,
                },
            )

        except httpx.TimeoutException:
            logger.warning(
                "chunk_summarization_timeout",
                chunk_id=str(chunk.chunk_id),
            )
            # Return original chunk on timeout
            return chunk

        except Exception as e:
            logger.warning(
                "chunk_summarization_error",
                chunk_id=str(chunk.chunk_id),
                error=str(e),
            )
            # Return original chunk on error
            return chunk

    async def batch_summarize(
        self,
        query: str,
        chunks: list[ChunkEvidence],
        batch_size: int = 3,
    ) -> list[ChunkEvidence]:
        """Summarize chunks in batches (alternative to concurrent approach).

        This can be more efficient when LLM costs are a concern,
        as it allows summarizing multiple chunks in one request.

        Args:
            query: The user's query
            chunks: Chunks to summarize
            batch_size: Number of chunks per batch

        Returns:
            List of summarized chunks
        """
        if not chunks:
            return []

        summarized = []

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            batch_result = await self._summarize_batch(query, batch)
            summarized.extend(batch_result)

        return summarized

    async def _summarize_batch(
        self,
        query: str,
        chunks: list[ChunkEvidence],
    ) -> list[ChunkEvidence]:
        """Summarize a batch of chunks in one LLM call."""
        # Build combined prompt
        chunks_text = "\n\n".join(
            f"[Chunk {i+1}]\n{chunk.text[:1000]}"
            for i, chunk in enumerate(chunks)
        )

        prompt = f"""You are extracting relevant information from scientific document chunks.

Query: {query}

{chunks_text}

For each chunk, extract ONLY information relevant to the query.
If a chunk has no relevant info, say "NO_RELEVANT_INFO" for that chunk.

Format your response as:
[Chunk 1]: <summary or NO_RELEVANT_INFO>
[Chunk 2]: <summary or NO_RELEVANT_INFO>
..."""

        try:
            response = await self.http_client.post(
                f"{self.settings.LLM_SERVICE_URL}/api/v1/generate",
                json={
                    "query": prompt,
                    "context": "",
                    "citations": [],
                    "intent": "SUMMARIZE",
                    "max_tokens": 500,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            result = response.json()
            answer = result.get("answer", "")

            # Parse batch response
            return self._parse_batch_response(answer, chunks)

        except Exception as e:
            logger.warning("batch_summarization_error", error=str(e))
            return chunks  # Return original chunks on error

    def _parse_batch_response(
        self,
        response: str,
        chunks: list[ChunkEvidence],
    ) -> list[ChunkEvidence]:
        """Parse batch summarization response."""
        summarized = []
        lines = response.split("\n")

        for i, chunk in enumerate(chunks):
            # Try to find summary for this chunk
            marker = f"[Chunk {i+1}]"
            summary = None

            for line in lines:
                if marker in line:
                    summary = line.split(":", 1)[-1].strip()
                    break

            if summary and "NO_RELEVANT_INFO" not in summary.upper():
                summarized.append(
                    ChunkEvidence(
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        text=summary,
                        section=chunk.section,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        similarity_score=chunk.similarity_score,
                        metadata={
                            **chunk.metadata,
                            "original_text": chunk.text[:500],
                            "summarized": True,
                        },
                    )
                )
            elif summary is None:
                # Couldn't parse, keep original
                summarized.append(chunk)
            # else: filtered as no relevant info

        return summarized
