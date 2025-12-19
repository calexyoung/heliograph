"""Graph API routes for Knowledge Extraction service."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.schemas import (
    EvidencePointer,
    GraphNode,
    GraphSearchRequest,
    GraphSearchResult,
    SubgraphRequest,
    SubgraphResponse,
)
from ...graph.neo4j_client import Neo4jClient
from ..deps import get_neo4j_client

router = APIRouter(prefix="/graph", tags=["graph"])


@router.post("/subgraph", response_model=SubgraphResponse)
async def get_subgraph(
    request: SubgraphRequest,
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> SubgraphResponse:
    """Get a subgraph centered on a node.

    Returns nodes and edges within the specified depth from the center node,
    filtered by node types, edge types, and minimum confidence.
    """
    return await neo4j.get_subgraph(
        center_node_id=request.center_node_id,
        depth=request.depth,
        node_types=request.node_types,
        edge_types=request.edge_types,
        min_confidence=request.min_confidence,
        max_nodes=request.max_nodes,
    )


@router.get("/subgraph/{node_id}", response_model=SubgraphResponse)
async def get_subgraph_by_id(
    node_id: str,
    depth: int = Query(default=2, ge=1, le=5),
    min_confidence: float = Query(default=0.5, ge=0.0, le=1.0),
    max_nodes: int = Query(default=100, ge=1, le=500),
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> SubgraphResponse:
    """Get a subgraph centered on a node by ID."""
    return await neo4j.get_subgraph(
        center_node_id=node_id,
        depth=depth,
        min_confidence=min_confidence,
        max_nodes=max_nodes,
    )


@router.post("/search", response_model=list[GraphSearchResult])
async def search_graph(
    request: GraphSearchRequest,
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> list[GraphSearchResult]:
    """Search for nodes in the knowledge graph.

    Performs full-text search on entity names and canonical names.
    """
    return await neo4j.search_nodes(
        query=request.query,
        node_type=request.node_type,
        limit=request.limit,
    )


@router.get("/search", response_model=list[GraphSearchResult])
async def search_graph_get(
    query: str,
    node_type: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> list[GraphSearchResult]:
    """Search for nodes in the knowledge graph (GET variant)."""
    return await neo4j.search_nodes(
        query=query,
        node_type=node_type,
        limit=limit,
    )


@router.get("/edges/{source_id}/{target_id}/evidence", response_model=list[EvidencePointer])
async def get_edge_evidence(
    source_id: str,
    target_id: str,
    relationship_type: str,
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> list[EvidencePointer]:
    """Get evidence for a specific edge in the graph.

    Returns the text snippets and chunk references that support
    the relationship between two nodes.
    """
    return await neo4j.get_edge_evidence(source_id, target_id, relationship_type)


@router.get("/documents/{document_id}/entities", response_model=list[GraphNode])
async def get_document_graph_entities(
    document_id: UUID,
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> list[GraphNode]:
    """Get all entities mentioned in a document from the graph."""
    return await neo4j.get_document_entities(document_id)


@router.get("/entities/{entity_id}/related", response_model=SubgraphResponse)
async def get_related_entities(
    entity_id: str,
    relationship_types: list[str] | None = Query(default=None),
    min_confidence: float = Query(default=0.5, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=200),
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> SubgraphResponse:
    """Get entities related to a specific entity.

    Returns a subgraph of depth 1 from the specified entity,
    optionally filtered by relationship types.
    """
    return await neo4j.get_subgraph(
        center_node_id=entity_id,
        depth=1,
        edge_types=relationship_types,
        min_confidence=min_confidence,
        max_nodes=limit,
    )


@router.get("/stats")
async def get_graph_stats(
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> dict:
    """Get statistics about the knowledge graph."""
    async with neo4j.driver.session() as session:
        # Count nodes
        node_result = await session.run(
            """
            MATCH (n)
            RETURN labels(n)[0] as label, count(n) as count
            """
        )
        node_counts = {}
        async for record in node_result:
            node_counts[record["label"]] = record["count"]

        # Count relationships
        rel_result = await session.run(
            """
            MATCH ()-[r]->()
            RETURN type(r) as type, count(r) as count
            """
        )
        rel_counts = {}
        async for record in rel_result:
            rel_counts[record["type"]] = record["count"]

        return {
            "nodes": node_counts,
            "relationships": rel_counts,
            "total_nodes": sum(node_counts.values()),
            "total_relationships": sum(rel_counts.values()),
        }
