"""Main query orchestrator that coordinates the RAG pipeline.

Implements a multi-stage RAG pipeline with:
1. Query parsing and understanding
2. Hybrid retrieval (dense + sparse vectors)
3. Re-ranking and diversity selection
4. Evidence summarization (paper-qa inspired)
5. Context assembly
6. LLM generation
"""

import time
from typing import AsyncIterator
from uuid import UUID

import httpx
import structlog

from ..config import Settings
from ..context.assembler import ContextAssembler, EvidenceTracker
from ..context.evidence_summarizer import EvidenceSummarizer
from ..context.reranker import MMRReranker, Reranker
from ..retrieval.graph_retriever import GraphRetriever
from ..retrieval.vector_retriever import VectorRetriever
from .query_parser import QueryParser
from .schemas import (
    ChunkEvidence,
    Citation,
    EvidenceMap,
    ParsedQuery,
    QueryRequest,
    QueryResponse,
    RetrievalResult,
    SearchFilters,
    StreamChunk,
)

logger = structlog.get_logger()


class QueryOrchestrator:
    """Orchestrates the full RAG pipeline.

    The pipeline includes:
    - Query parsing with intent detection
    - Hybrid vector + sparse retrieval
    - Cross-encoder reranking
    - MMR diversity selection
    - Evidence summarization (extracts query-relevant info)
    - Context assembly with token management
    - LLM generation with citations
    """

    def __init__(self, settings: Settings):
        """Initialize the query orchestrator."""
        self.settings = settings
        self.query_parser = QueryParser(settings)
        self.vector_retriever = VectorRetriever(settings)
        self.graph_retriever = GraphRetriever(settings)
        self.reranker = Reranker(settings)
        self.mmr_reranker = MMRReranker()
        self.context_assembler = ContextAssembler(settings)
        self.http_client = httpx.AsyncClient(timeout=60.0)
        self.evidence_summarizer = EvidenceSummarizer(settings, self.http_client)

    async def initialize(self) -> None:
        """Initialize connections."""
        await self.graph_retriever.connect()

    async def close(self) -> None:
        """Close all connections."""
        await self.vector_retriever.close()
        await self.graph_retriever.close()
        await self.evidence_summarizer.close()
        await self.http_client.aclose()

    async def query(self, request: QueryRequest) -> QueryResponse:
        """Process a query through the full RAG pipeline.

        Args:
            request: The query request

        Returns:
            QueryResponse with answer, citations, and evidence
        """
        start_time = time.time()

        # Step 1: Parse and understand the query
        parsed_query = self.query_parser.parse(request.query)
        logger.info(
            "Query parsed",
            intent=parsed_query.intent,
            entities=parsed_query.entities,
        )

        # Step 2: Retrieve relevant chunks
        retrieval_result = await self._retrieve(parsed_query, request)
        logger.info(
            "Retrieval complete",
            chunks_retrieved=len(retrieval_result.evidence.chunks),
        )

        # Step 3: Assemble context
        context, citations = self.context_assembler.assemble_context(
            retrieval_result.evidence.chunks,
            retrieval_result.evidence.graph_paths,
        )

        # Step 4: Generate response via LLM service
        answer, confidence = await self._generate_response(
            request.query,
            context,
            citations,
            parsed_query,
        )

        processing_time = (time.time() - start_time) * 1000

        return QueryResponse(
            answer=answer,
            citations=citations,
            evidence=retrieval_result.evidence,
            confidence=confidence,
            query_intent=parsed_query.intent,
            processing_time_ms=processing_time,
        )

    async def query_stream(
        self, request: QueryRequest
    ) -> AsyncIterator[StreamChunk]:
        """Process a query with streaming response.

        Args:
            request: The query request

        Yields:
            StreamChunk objects as response is generated
        """
        # Step 1: Parse query
        parsed_query = self.query_parser.parse(request.query)

        # Step 2: Retrieve
        retrieval_result = await self._retrieve(parsed_query, request)

        # Yield evidence update
        yield StreamChunk(
            type="evidence",
            evidence_update=retrieval_result.evidence.chunks[:5],
        )

        # Step 3: Assemble context
        context, citations = self.context_assembler.assemble_context(
            retrieval_result.evidence.chunks,
            retrieval_result.evidence.graph_paths,
        )

        # Step 4: Stream generation
        async for chunk in self._generate_stream(
            request.query, context, citations, parsed_query
        ):
            yield chunk

        # Final chunk
        yield StreamChunk(type="done")

    async def _retrieve(
        self,
        parsed_query: ParsedQuery,
        request: QueryRequest,
    ) -> RetrievalResult:
        """Perform retrieval stage with query fusion.

        Uses multiple query variations and merges results for better recall.

        Args:
            parsed_query: The parsed query
            request: Original query request

        Returns:
            RetrievalResult with evidence
        """
        start_time = time.time()

        # Build search filters from constraints
        filters = SearchFilters(
            document_ids=[str(d) for d in request.corpus_ids] if request.corpus_ids else None,
            year_min=parsed_query.constraints.year_start,
            year_max=parsed_query.constraints.year_end,
        )

        # Generate query variations for fusion
        query_variations = self.query_parser.generate_query_variations(
            parsed_query.original_query
        )

        # Add rewritten query if available and different
        if parsed_query.rewritten_query and parsed_query.rewritten_query not in query_variations:
            query_variations.append(parsed_query.rewritten_query)

        # Perform fusion retrieval - search with multiple queries and merge
        all_chunks: dict[str, ChunkEvidence] = {}
        chunk_scores: dict[str, list[float]] = {}

        for search_query in query_variations[:3]:  # Limit to 3 variations
            chunks = await self.vector_retriever.search(
                search_query,
                top_k=self.settings.VECTOR_TOP_K,
                filters=filters,
            )

            for chunk in chunks:
                chunk_key = str(chunk.chunk_id)
                if chunk_key not in all_chunks:
                    all_chunks[chunk_key] = chunk
                    chunk_scores[chunk_key] = []
                chunk_scores[chunk_key].append(chunk.similarity_score)

        # Reciprocal Rank Fusion (RRF) scoring
        k = 60  # RRF constant
        for chunk_key, chunk in all_chunks.items():
            scores = chunk_scores[chunk_key]
            # RRF: sum of 1/(k + rank) for each query where chunk appears
            rrf_score = sum(1.0 / (k + i + 1) for i, _ in enumerate(scores))
            # Also factor in average similarity
            avg_similarity = sum(scores) / len(scores)
            # Combined score
            chunk.similarity_score = (rrf_score * 0.6) + (avg_similarity * 0.4)

        # Sort by combined score and take top results
        chunks = sorted(
            all_chunks.values(),
            key=lambda c: c.similarity_score,
            reverse=True
        )[:self.settings.VECTOR_TOP_K]

        # Graph expansion if enabled
        graph_paths = []
        if request.include_graph and parsed_query.entities:
            chunks, graph_paths = await self.graph_retriever.expand_with_graph(
                chunks, parsed_query
            )

        # Re-rank
        if self.settings.RERANK_ENABLED and chunks:
            chunks = self.reranker.rerank(
                parsed_query.original_query,
                chunks,
                top_k=self.settings.RERANK_TOP_K,
            )

        # Apply MMR for diversity
        chunks = self.mmr_reranker.rerank_mmr(
            parsed_query.original_query,
            chunks,
            top_k=request.max_results,
        )

        # Select diverse chunks for context
        chunks = self.context_assembler.select_diverse_chunks(chunks)

        # Evidence summarization - extract query-relevant info from each chunk
        if getattr(self.settings, "ENABLE_EVIDENCE_SUMMARIZATION", True) and chunks:
            max_concurrent = getattr(
                self.settings, "EVIDENCE_SUMMARIZATION_MAX_CONCURRENT", 5
            )
            chunks = await self.evidence_summarizer.summarize_evidence(
                parsed_query.original_query,
                chunks,
                max_concurrent=max_concurrent,
            )
            logger.info(
                "Evidence summarization complete",
                chunks_after_summarization=len(chunks),
            )

        retrieval_time = (time.time() - start_time) * 1000

        return RetrievalResult(
            query=parsed_query,
            evidence=EvidenceMap(
                chunks=chunks,
                graph_paths=graph_paths,
                total_chunks_retrieved=self.settings.VECTOR_TOP_K,
                total_chunks_after_rerank=len(chunks),
            ),
            retrieval_time_ms=retrieval_time,
        )

    async def _generate_response(
        self,
        query: str,
        context: str,
        citations: list[Citation],
        parsed_query: ParsedQuery,
    ) -> tuple[str, float]:
        """Generate response using LLM service.

        Args:
            query: Original query
            context: Assembled context
            citations: Available citations
            parsed_query: Parsed query info

        Returns:
            Tuple of (answer, confidence)
        """
        try:
            response = await self.http_client.post(
                f"{self.settings.LLM_SERVICE_URL}/api/v1/generate",
                json={
                    "query": query,
                    "context": context,
                    "citations": [c.model_dump(mode="json") for c in citations],
                    "intent": parsed_query.intent.value,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            result = response.json()

            return result.get("answer", ""), result.get("confidence", 0.5)

        except Exception as e:
            logger.error("LLM generation failed", error=str(e))
            # Fallback response
            return self._generate_fallback_response(context, citations), 0.3

    async def _generate_stream(
        self,
        query: str,
        context: str,
        citations: list[Citation],
        parsed_query: ParsedQuery,
    ) -> AsyncIterator[StreamChunk]:
        """Stream generation from LLM service.

        Args:
            query: Original query
            context: Assembled context
            citations: Available citations
            parsed_query: Parsed query info

        Yields:
            StreamChunk objects
        """
        try:
            async with self.http_client.stream(
                "POST",
                f"{self.settings.LLM_SERVICE_URL}/api/v1/generate/stream",
                json={
                    "query": query,
                    "context": context,
                    "citations": [c.model_dump(mode="json") for c in citations],
                    "intent": parsed_query.intent.value,
                },
                timeout=60.0,
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        import json

                        data = json.loads(line[6:])
                        if data.get("type") == "text":
                            yield StreamChunk(type="text", content=data.get("content"))
                        elif data.get("type") == "citation":
                            # Find matching citation
                            cit_id = data.get("citation_id")
                            if cit_id and cit_id <= len(citations):
                                yield StreamChunk(
                                    type="citation",
                                    citation=citations[cit_id - 1],
                                )

        except Exception as e:
            logger.error("Streaming generation failed", error=str(e))
            yield StreamChunk(
                type="text",
                content="I encountered an error while generating the response.",
            )

    def _generate_fallback_response(
        self,
        context: str,
        citations: list[Citation],
    ) -> str:
        """Generate a fallback response when LLM service is unavailable."""
        if not citations:
            return "I couldn't find relevant information to answer your question."

        response_parts = [
            "Based on the retrieved documents, here are the relevant excerpts:\n"
        ]

        for cit in citations[:3]:
            response_parts.append(f"\n[{cit.citation_id}] {cit.snippet}")

        return "".join(response_parts)
