"""Graph-augmented retrieval using Neo4j."""

from typing import Any
from uuid import UUID

import structlog
from neo4j import AsyncGraphDatabase, AsyncDriver

from ..config import Settings
from ..core.schemas import ChunkEvidence, GraphPath, ParsedQuery

logger = structlog.get_logger()


class GraphRetriever:
    """Retrieves relevant information using knowledge graph."""

    def __init__(self, settings: Settings):
        """Initialize the graph retriever."""
        self.settings = settings
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        """Connect to Neo4j database."""
        self._driver = AsyncGraphDatabase.driver(
            self.settings.NEO4J_URI,
            auth=(self.settings.NEO4J_USER, self.settings.NEO4J_PASSWORD),
        )

    async def close(self) -> None:
        """Close the Neo4j connection."""
        if self._driver:
            await self._driver.close()
            self._driver = None

    @property
    def driver(self) -> AsyncDriver:
        """Get the Neo4j driver."""
        if not self._driver:
            raise RuntimeError("Graph retriever not connected")
        return self._driver

    async def expand_with_graph(
        self,
        chunks: list[ChunkEvidence],
        parsed_query: ParsedQuery,
    ) -> tuple[list[ChunkEvidence], list[GraphPath]]:
        """Expand retrieval results using knowledge graph.

        Args:
            chunks: Initial chunks from vector search
            parsed_query: The parsed query with entities

        Returns:
            Tuple of (expanded chunks, graph paths)
        """
        if not chunks:
            return chunks, []

        # Get document IDs from initial chunks
        doc_ids = list(set(str(c.document_id) for c in chunks))

        # Find entities mentioned in these documents
        entity_paths = await self._find_entity_connections(
            parsed_query.entities, doc_ids
        )

        # Get additional documents through graph expansion
        expanded_doc_ids = await self._expand_through_graph(
            doc_ids, parsed_query.entities
        )

        # Return original chunks with graph paths
        # In a full implementation, we'd fetch additional chunks from expanded docs
        return chunks, entity_paths

    async def _find_entity_connections(
        self,
        entities: list[str],
        document_ids: list[str],
    ) -> list[GraphPath]:
        """Find connections between entities in the graph."""
        if not entities:
            return []

        paths = []
        async with self.driver.session() as session:
            for entity in entities:
                result = await session.run(
                    """
                    MATCH (a:Article)-[:MENTIONS]->(e:Entity)
                    WHERE a.document_id IN $doc_ids
                      AND (e.name =~ $entity_pattern OR e.canonical_name =~ $entity_pattern)
                    OPTIONAL MATCH path = (e)-[rel]-(other:Entity)
                    WHERE rel.confidence IS NULL OR rel.confidence > 0.5
                    RETURN e.name as entity,
                           [n in nodes(path) | n.name] as path_nodes,
                           [r in relationships(path) | type(r)] as path_edges,
                           coalesce(rel.confidence, 1.0) as avg_confidence
                    LIMIT 10
                    """,
                    doc_ids=document_ids,
                    entity_pattern=f"(?i).*{entity}.*",
                )

                async for record in result:
                    if record["path_nodes"] and len(record["path_nodes"]) > 1:
                        paths.append(
                            GraphPath(
                                nodes=record["path_nodes"],
                                edges=record["path_edges"] or [],
                                confidence=record["avg_confidence"] or 0.5,
                            )
                        )

        return paths

    async def _expand_through_graph(
        self,
        document_ids: list[str],
        entities: list[str],
    ) -> list[str]:
        """Find additional documents through graph connections."""
        expanded_ids = set(document_ids)

        async with self.driver.session() as session:
            # Find documents that share entities with the initial set
            result = await session.run(
                """
                MATCH (a1:Article)-[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(a2:Article)
                WHERE a1.document_id IN $doc_ids
                  AND NOT a2.document_id IN $doc_ids
                WITH a2, count(e) as shared_entities
                WHERE shared_entities >= 2
                RETURN a2.document_id as doc_id
                ORDER BY shared_entities DESC
                LIMIT $max_expansion
                """,
                doc_ids=document_ids,
                max_expansion=self.settings.GRAPH_MAX_NODES,
            )

            async for record in result:
                expanded_ids.add(record["doc_id"])

            # If entities specified, find documents mentioning them
            if entities:
                for entity in entities[:3]:  # Limit entity expansion
                    result = await session.run(
                        """
                        MATCH (a:Article)-[:MENTIONS]->(e:Entity)
                        WHERE (e.name =~ $entity_pattern OR e.canonical_name =~ $entity_pattern)
                          AND NOT a.document_id IN $doc_ids
                        RETURN a.document_id as doc_id
                        LIMIT 5
                        """,
                        entity_pattern=f"(?i).*{entity}.*",
                        doc_ids=list(expanded_ids),
                    )

                    async for record in result:
                        expanded_ids.add(record["doc_id"])

        return list(expanded_ids)

    async def find_citing_documents(
        self, document_id: UUID
    ) -> list[dict[str, Any]]:
        """Find documents that cite a specific document."""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (citing:Article)-[:CITES]->(cited:Article {document_id: $doc_id})
                RETURN citing.document_id as document_id,
                       citing.title as title,
                       citing.year as year
                ORDER BY citing.year DESC
                LIMIT 20
                """,
                doc_id=str(document_id),
            )

            docs = []
            async for record in result:
                docs.append({
                    "document_id": record["document_id"],
                    "title": record["title"],
                    "year": record["year"],
                })

            return docs

    async def find_related_by_entities(
        self,
        document_id: UUID,
        min_shared: int = 2,
    ) -> list[dict[str, Any]]:
        """Find documents that share entities with a document."""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (a1:Article {document_id: $doc_id})-[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(a2:Article)
                WHERE a1 <> a2
                WITH a2, collect(e.name) as shared_entities
                WHERE size(shared_entities) >= $min_shared
                RETURN a2.document_id as document_id,
                       a2.title as title,
                       a2.year as year,
                       shared_entities
                ORDER BY size(shared_entities) DESC
                LIMIT 20
                """,
                doc_id=str(document_id),
                min_shared=min_shared,
            )

            docs = []
            async for record in result:
                docs.append({
                    "document_id": record["document_id"],
                    "title": record["title"],
                    "year": record["year"],
                    "shared_entities": record["shared_entities"],
                })

            return docs
