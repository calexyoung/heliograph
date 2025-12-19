"""Neo4j graph database client for knowledge graph operations."""

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from neo4j import AsyncGraphDatabase, AsyncDriver
from neo4j.time import DateTime as Neo4jDateTime

from ..config import Settings
from ..core.schemas import (
    EntityType,
    ExtractedEntity,
    ExtractedRelationship,
    EvidencePointer,
    GraphEdge,
    GraphNode,
    GraphSearchResult,
    RelationshipType,
    SubgraphResponse,
)

logger = structlog.get_logger()


class Neo4jClient:
    """Client for Neo4j graph database operations."""

    def __init__(self, settings: Settings):
        """Initialize the Neo4j client."""
        self.settings = settings
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        """Connect to Neo4j database."""
        self._driver = AsyncGraphDatabase.driver(
            self.settings.NEO4J_URI,
            auth=(self.settings.NEO4J_USER, self.settings.NEO4J_PASSWORD),
        )
        # Verify connectivity
        async with self._driver.session() as session:
            await session.run("RETURN 1")
        logger.info("Connected to Neo4j", uri=self.settings.NEO4J_URI)

    async def close(self) -> None:
        """Close the Neo4j connection."""
        if self._driver:
            await self._driver.close()
            self._driver = None

    @property
    def driver(self) -> AsyncDriver:
        """Get the Neo4j driver."""
        if not self._driver:
            raise RuntimeError("Neo4j client not connected")
        return self._driver

    async def setup_schema(self) -> None:
        """Set up Neo4j schema with indexes and constraints."""
        async with self.driver.session() as session:
            # Create constraints
            await session.run(
                "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE"
            )
            await session.run(
                "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (a:Article) REQUIRE a.document_id IS UNIQUE"
            )

            # Create indexes
            await session.run(
                "CREATE INDEX entity_canonical IF NOT EXISTS FOR (e:Entity) ON (e.canonical_name)"
            )
            await session.run(
                "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.entity_type)"
            )
            await session.run(
                "CREATE INDEX article_year IF NOT EXISTS FOR (a:Article) ON (a.year)"
            )

            # Create full-text index for search
            await session.run(
                """
                CREATE FULLTEXT INDEX entity_search IF NOT EXISTS
                FOR (e:Entity) ON EACH [e.name, e.canonical_name]
                """
            )

        logger.info("Neo4j schema setup complete")

    # Entity operations
    async def upsert_entity(self, entity: ExtractedEntity) -> str:
        """Upsert an entity node in the graph."""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MERGE (e:Entity {canonical_name: $canonical_name, entity_type: $entity_type})
                ON CREATE SET
                    e.entity_id = $entity_id,
                    e.name = $name,
                    e.aliases = $aliases,
                    e.created_at = datetime()
                ON MATCH SET
                    e.aliases = CASE
                        WHEN e.aliases IS NULL THEN $aliases
                        ELSE [x IN e.aliases WHERE NOT x IN $aliases] + $aliases
                    END,
                    e.updated_at = datetime()
                RETURN e.entity_id as entity_id
                """,
                entity_id=str(entity.entity_id),
                canonical_name=entity.canonical_name,
                name=entity.name,
                entity_type=entity.entity_type.value,
                aliases=entity.aliases,
            )
            record = await result.single()
            return record["entity_id"] if record else str(entity.entity_id)

    async def upsert_article(
        self,
        document_id: UUID,
        title: str,
        year: int | None = None,
        doi: str | None = None,
        authors: list[str] | None = None,
    ) -> str:
        """Upsert an article node in the graph."""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MERGE (a:Article {document_id: $document_id})
                ON CREATE SET
                    a.title = $title,
                    a.year = $year,
                    a.doi = $doi,
                    a.authors = $authors,
                    a.created_at = datetime()
                ON MATCH SET
                    a.title = $title,
                    a.year = $year,
                    a.doi = $doi,
                    a.authors = $authors,
                    a.updated_at = datetime()
                RETURN a.document_id as document_id
                """,
                document_id=str(document_id),
                title=title,
                year=year,
                doi=doi,
                authors=authors or [],
            )
            record = await result.single()
            return record["document_id"] if record else str(document_id)

    async def create_mention_relationship(
        self,
        document_id: UUID,
        entity: ExtractedEntity,
        chunk_id: UUID,
        confidence: float,
    ) -> None:
        """Create a MENTIONS relationship between article and entity."""
        async with self.driver.session() as session:
            await session.run(
                """
                MATCH (a:Article {document_id: $document_id})
                MATCH (e:Entity {canonical_name: $canonical_name, entity_type: $entity_type})
                MERGE (a)-[r:MENTIONS]->(e)
                ON CREATE SET
                    r.chunk_ids = [$chunk_id],
                    r.confidence = $confidence,
                    r.created_at = datetime()
                ON MATCH SET
                    r.chunk_ids = CASE
                        WHEN NOT $chunk_id IN r.chunk_ids THEN r.chunk_ids + $chunk_id
                        ELSE r.chunk_ids
                    END,
                    r.confidence = CASE
                        WHEN $confidence > r.confidence THEN $confidence
                        ELSE r.confidence
                    END
                """,
                document_id=str(document_id),
                canonical_name=entity.canonical_name,
                entity_type=entity.entity_type.value,
                chunk_id=str(chunk_id),
                confidence=confidence,
            )

    async def create_relationship(
        self,
        relationship: ExtractedRelationship,
        source_entity: ExtractedEntity,
        target_entity: ExtractedEntity,
    ) -> None:
        """Create a relationship between two entities."""
        rel_type = relationship.relationship_type.value.upper()

        # Serialize evidence
        evidence_data = [
            {
                "chunk_id": str(e.chunk_id),
                "document_id": str(e.document_id),
                "char_start": e.char_start,
                "char_end": e.char_end,
                "snippet": e.snippet,
            }
            for e in relationship.evidence
        ]

        async with self.driver.session() as session:
            await session.run(
                f"""
                MATCH (s:Entity {{canonical_name: $source_canonical, entity_type: $source_type}})
                MATCH (t:Entity {{canonical_name: $target_canonical, entity_type: $target_type}})
                MERGE (s)-[r:{rel_type}]->(t)
                ON CREATE SET
                    r.confidence = $confidence,
                    r.evidence = $evidence,
                    r.created_at = datetime()
                ON MATCH SET
                    r.confidence = CASE
                        WHEN $confidence > r.confidence THEN $confidence
                        ELSE r.confidence
                    END,
                    r.evidence = r.evidence + $evidence
                """,
                source_canonical=source_entity.canonical_name,
                source_type=source_entity.entity_type.value,
                target_canonical=target_entity.canonical_name,
                target_type=target_entity.entity_type.value,
                confidence=relationship.confidence,
                evidence=evidence_data,
            )

    # Query operations
    async def get_subgraph(
        self,
        center_node_id: str,
        depth: int = 2,
        node_types: list[str] | None = None,
        edge_types: list[str] | None = None,
        min_confidence: float = 0.5,
        max_nodes: int = 100,
    ) -> SubgraphResponse:
        """Get a subgraph centered on a node."""
        # Build type filters
        node_filter = ""
        if node_types:
            labels = " OR ".join([f"n:{t}" for t in node_types])
            node_filter = f"WHERE ({labels})"

        edge_filter = ""
        if edge_types:
            edge_filter = f"WHERE type(r) IN {edge_types}"

        async with self.driver.session() as session:
            # Find center node
            center_result = await session.run(
                """
                MATCH (n)
                WHERE n.entity_id = $node_id OR n.document_id = $node_id
                RETURN n, labels(n) as labels
                LIMIT 1
                """,
                node_id=center_node_id,
            )
            center_record = await center_result.single()

            if not center_record:
                return SubgraphResponse(nodes=[], edges=[], center_node=None)

            center_node = self._node_to_graph_node(
                center_record["n"], center_record["labels"]
            )

            # Get subgraph
            result = await session.run(
                f"""
                MATCH (center)
                WHERE center.entity_id = $node_id OR center.document_id = $node_id
                CALL apoc.path.subgraphAll(center, {{
                    maxLevel: $depth,
                    relationshipFilter: null,
                    minLevel: 1
                }})
                YIELD nodes, relationships
                UNWIND nodes as n
                WITH DISTINCT n, relationships
                {node_filter}
                WITH collect(DISTINCT n) as allNodes, relationships
                UNWIND relationships as r
                WITH allNodes, r
                WHERE r.confidence IS NULL OR r.confidence >= $min_confidence
                RETURN allNodes, collect(DISTINCT r) as allRels
                """,
                node_id=center_node_id,
                depth=depth,
                min_confidence=min_confidence,
            )

            record = await result.single()
            if not record:
                return SubgraphResponse(nodes=[center_node], edges=[], center_node=center_node)

            # Convert nodes
            nodes = [center_node]
            seen_ids = {center_node.node_id}

            for node in record["allNodes"][:max_nodes]:
                labels = list(node.labels)
                graph_node = self._node_to_graph_node(node, labels)
                if graph_node.node_id not in seen_ids:
                    nodes.append(graph_node)
                    seen_ids.add(graph_node.node_id)

            # Convert edges
            edges = []
            evidence_refs: dict[str, list[EvidencePointer]] = {}

            for rel in record["allRels"]:
                edge = self._rel_to_graph_edge(rel)
                edges.append(edge)

                # Extract evidence
                if rel.get("evidence"):
                    evidence_refs[edge.edge_id] = [
                        EvidencePointer(
                            chunk_id=UUID(e["chunk_id"]),
                            document_id=UUID(e["document_id"]),
                            char_start=e["char_start"],
                            char_end=e["char_end"],
                            snippet=e["snippet"],
                        )
                        for e in rel["evidence"]
                        if isinstance(e, dict)
                    ]

            return SubgraphResponse(
                nodes=nodes,
                edges=edges,
                center_node=center_node,
                evidence_refs=evidence_refs,
            )

    async def search_nodes(
        self,
        query: str,
        node_type: str | None = None,
        limit: int = 20,
    ) -> list[GraphSearchResult]:
        """Search for nodes by text query."""
        async with self.driver.session() as session:
            # Use full-text search
            type_filter = ""
            if node_type:
                type_filter = f"AND n.entity_type = '{node_type}'"

            result = await session.run(
                f"""
                CALL db.index.fulltext.queryNodes('entity_search', $search_term)
                YIELD node, score
                WHERE score > 0.1 {type_filter}
                RETURN node, score, labels(node) as labels
                ORDER BY score DESC
                LIMIT $limit
                """,
                search_term=query,
                limit=limit,
            )

            results = []
            async for record in result:
                node = self._node_to_graph_node(record["node"], record["labels"])
                matched = record["node"].get("name", record["node"].get("title", ""))
                results.append(
                    GraphSearchResult(
                        node=node,
                        score=record["score"],
                        matched_text=matched,
                    )
                )

            return results

    async def get_edge_evidence(
        self, source_id: str, target_id: str, relationship_type: str
    ) -> list[EvidencePointer]:
        """Get evidence for a specific edge."""
        async with self.driver.session() as session:
            result = await session.run(
                f"""
                MATCH (s)-[r:{relationship_type.upper()}]->(t)
                WHERE (s.entity_id = $source_id OR s.document_id = $source_id)
                  AND (t.entity_id = $target_id OR t.document_id = $target_id)
                RETURN r.evidence as evidence
                """,
                source_id=source_id,
                target_id=target_id,
            )

            record = await result.single()
            if not record or not record["evidence"]:
                return []

            return [
                EvidencePointer(
                    chunk_id=UUID(e["chunk_id"]),
                    document_id=UUID(e["document_id"]),
                    char_start=e["char_start"],
                    char_end=e["char_end"],
                    snippet=e["snippet"],
                )
                for e in record["evidence"]
                if isinstance(e, dict)
            ]

    async def get_document_entities(self, document_id: UUID) -> list[GraphNode]:
        """Get all entities mentioned in a document."""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (a:Article {document_id: $document_id})-[:MENTIONS]->(e:Entity)
                RETURN e, labels(e) as labels
                """,
                document_id=str(document_id),
            )

            nodes = []
            async for record in result:
                nodes.append(self._node_to_graph_node(record["e"], record["labels"]))

            return nodes

    def _convert_neo4j_value(self, value: Any) -> Any:
        """Convert Neo4j types to Python-native serializable types."""
        if isinstance(value, Neo4jDateTime):
            return value.to_native()
        if isinstance(value, list):
            return [self._convert_neo4j_value(v) for v in value]
        if isinstance(value, dict):
            return {k: self._convert_neo4j_value(v) for k, v in value.items()}
        return value

    def _node_to_graph_node(self, node: Any, labels: list[str]) -> GraphNode:
        """Convert a Neo4j node to GraphNode."""
        props = dict(node)
        node_id = props.get("entity_id") or props.get("document_id") or str(id(node))
        label = props.get("name") or props.get("title") or str(node_id)[:8]
        node_type = "article" if "Article" in labels else "entity"

        # Convert properties to serializable types
        serializable_props = {
            k: self._convert_neo4j_value(v)
            for k, v in props.items()
            if k not in ["entity_id", "document_id"]
        }

        return GraphNode(
            node_id=str(node_id),
            entity_id=UUID(props["entity_id"]) if props.get("entity_id") else None,
            document_id=UUID(props["document_id"]) if props.get("document_id") else None,
            label=label,
            node_type=node_type,
            properties=serializable_props,
        )

    def _rel_to_graph_edge(self, rel: Any) -> GraphEdge:
        """Convert a Neo4j relationship to GraphEdge."""
        props = dict(rel)
        start_node = rel.start_node
        end_node = rel.end_node

        source_id = (
            start_node.get("entity_id")
            or start_node.get("document_id")
            or str(id(start_node))
        )
        target_id = (
            end_node.get("entity_id")
            or end_node.get("document_id")
            or str(id(end_node))
        )

        # Convert properties to serializable types
        serializable_props = {
            k: self._convert_neo4j_value(v)
            for k, v in props.items()
            if k not in ["confidence", "evidence"]
        }

        return GraphEdge(
            edge_id=f"{source_id}-{rel.type}-{target_id}",
            source_id=str(source_id),
            target_id=str(target_id),
            relationship_type=rel.type.lower(),
            confidence=props.get("confidence", 1.0),
            properties=serializable_props,
        )
