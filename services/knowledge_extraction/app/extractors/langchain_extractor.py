"""LangChain-based knowledge graph extraction using LLMGraphTransformer.

This module provides an alternative extraction approach using LangChain's
experimental graph transformers, inspired by:
https://github.com/calexyoung/knowledge-graph-llms

Key benefits over custom prompt-based extraction:
- Single-pass extraction of entities and relationships
- Constrained extraction with allowed_nodes and allowed_relationships
- Well-tested LangChain abstractions
- Structured output with Node and Relationship objects
"""

from typing import Any
from uuid import UUID, uuid4

import structlog

from ..config import Settings
from ..core.schemas import (
    EntityMention,
    EntityType,
    EvidencePointer,
    ExtractedEntity,
    ExtractedRelationship,
    RelationshipType,
)

logger = structlog.get_logger()

# Heliophysics-specific allowed node types
HELIOPHYSICS_NODE_TYPES = [
    "ScientificConcept",
    "Method",
    "Dataset",
    "Instrument",
    "Phenomenon",
    "Mission",
    "Spacecraft",
    "CelestialBody",
    "Organization",
    "Person",
]

# Heliophysics-specific allowed relationships as triplets
# Format: (source_type, relationship, target_type)
HELIOPHYSICS_RELATIONSHIPS = [
    # Observation relationships
    ("Mission", "OBSERVES", "Phenomenon"),
    ("Mission", "OBSERVES", "CelestialBody"),
    ("Instrument", "OBSERVES", "Phenomenon"),
    ("Instrument", "DETECTS", "Phenomenon"),
    ("Spacecraft", "OBSERVES", "CelestialBody"),
    # Composition relationships
    ("Instrument", "PART_OF", "Mission"),
    ("Instrument", "PART_OF", "Spacecraft"),
    ("Spacecraft", "PART_OF", "Mission"),
    # Study relationships
    ("Method", "STUDIES", "Phenomenon"),
    ("Method", "ANALYZES", "Dataset"),
    ("Dataset", "CONTAINS", "Phenomenon"),
    # Causal relationships
    ("Phenomenon", "CAUSES", "Phenomenon"),
    ("CelestialBody", "PRODUCES", "Phenomenon"),
    # Operational relationships
    ("Organization", "OPERATES", "Mission"),
    ("Organization", "OPERATES", "Spacecraft"),
    ("Organization", "BUILT", "Instrument"),
    # Data relationships
    ("Mission", "PRODUCES", "Dataset"),
    ("Instrument", "PRODUCES", "Dataset"),
    # Scientific relationships
    ("ScientificConcept", "RELATED_TO", "ScientificConcept"),
    ("ScientificConcept", "DESCRIBES", "Phenomenon"),
    ("Method", "USES", "Instrument"),
    # Location relationships
    ("Mission", "ORBITS", "CelestialBody"),
    ("Spacecraft", "ORBITS", "CelestialBody"),
    ("Phenomenon", "OCCURS_AT", "CelestialBody"),
]


class LangChainGraphExtractor:
    """Extract knowledge graph using LangChain's LLMGraphTransformer.

    This extractor provides:
    - Single-pass entity and relationship extraction
    - Constrained extraction for heliophysics domain
    - Better structured output
    """

    def __init__(self, settings: Settings):
        """Initialize the LangChain graph extractor."""
        self.settings = settings
        self._transformer = None
        self._llm = None

    def _get_transformer(self) -> Any:
        """Lazy-load the LangChain graph transformer."""
        if self._transformer is None:
            try:
                from langchain_experimental.graph_transformers import LLMGraphTransformer
                from langchain_openai import ChatOpenAI

                # Initialize LLM
                if self.settings.EXTRACTION_PROVIDER == "openai":
                    self._llm = ChatOpenAI(
                        model=self.settings.EXTRACTION_MODEL,
                        temperature=0.0,
                        api_key=self.settings.OPENAI_API_KEY,
                    )
                else:
                    # Default to OpenAI for LangChain transformer
                    logger.warning(
                        "LangChain extractor currently supports OpenAI only, "
                        "falling back to OpenAI"
                    )
                    self._llm = ChatOpenAI(
                        model="gpt-4o",
                        temperature=0.0,
                        api_key=self.settings.OPENAI_API_KEY,
                    )

                # Create transformer with heliophysics constraints
                if self.settings.CONSTRAINED_EXTRACTION:
                    self._transformer = LLMGraphTransformer(
                        llm=self._llm,
                        allowed_nodes=HELIOPHYSICS_NODE_TYPES,
                        allowed_relationships=[
                            rel[1] for rel in HELIOPHYSICS_RELATIONSHIPS
                        ],
                    )
                else:
                    self._transformer = LLMGraphTransformer(llm=self._llm)

                logger.info(
                    "Initialized LangChain graph transformer",
                    model=self.settings.EXTRACTION_MODEL,
                    constrained=self.settings.CONSTRAINED_EXTRACTION,
                )

            except ImportError as e:
                logger.error(
                    "LangChain dependencies not installed. "
                    "Install with: pip install langchain-experimental langchain-openai",
                    error=str(e),
                )
                raise

        return self._transformer

    async def extract(
        self,
        text: str,
        chunk_id: UUID,
        document_id: UUID,
    ) -> tuple[list[ExtractedEntity], list[ExtractedRelationship]]:
        """Extract entities and relationships in a single pass.

        Args:
            text: The text to extract from
            chunk_id: The chunk ID
            document_id: The document ID

        Returns:
            Tuple of (entities, relationships)
        """
        try:
            from langchain_core.documents import Document

            transformer = self._get_transformer()

            # Convert text to LangChain Document
            doc = Document(page_content=text)

            # Extract graph - this is sync in LangChain, run in executor
            import asyncio
            loop = asyncio.get_event_loop()
            graph_documents = await loop.run_in_executor(
                None,
                transformer.convert_to_graph_documents,
                [doc],
            )

            if not graph_documents:
                return [], []

            graph_doc = graph_documents[0]

            # Convert LangChain nodes to our ExtractedEntity format
            entities = self._convert_nodes(
                graph_doc.nodes, text, chunk_id, document_id
            )

            # Convert LangChain relationships to our format
            relationships = self._convert_relationships(
                graph_doc.relationships, entities, chunk_id, document_id
            )

            logger.info(
                "LangChain extraction complete",
                entities=len(entities),
                relationships=len(relationships),
            )

            return entities, relationships

        except Exception as e:
            logger.error("LangChain extraction failed", error=str(e))
            return [], []

    def _convert_nodes(
        self,
        nodes: list[Any],
        text: str,
        chunk_id: UUID,
        document_id: UUID,
    ) -> list[ExtractedEntity]:
        """Convert LangChain nodes to ExtractedEntity objects."""
        entities = []

        for node in nodes:
            try:
                # Map LangChain node type to our EntityType
                entity_type = self._map_node_type(node.type)
                if entity_type is None:
                    continue

                # Find mention position in text
                name = node.id
                char_start = text.lower().find(name.lower())
                char_end = char_start + len(name) if char_start >= 0 else 0

                mention = EntityMention(
                    chunk_id=chunk_id,
                    text=name,
                    char_start=max(0, char_start),
                    char_end=char_end if char_end > 0 else len(name),
                    confidence=0.9,  # LangChain doesn't provide confidence
                )

                entity = ExtractedEntity(
                    entity_id=uuid4(),
                    name=name,
                    canonical_name=name.lower(),
                    entity_type=entity_type,
                    confidence=0.9,
                    aliases=[],
                    mentions=[mention],
                    metadata={
                        "document_id": str(document_id),
                        "langchain_type": node.type,
                    },
                )
                entities.append(entity)

            except Exception as e:
                logger.warning("Failed to convert node", error=str(e), node=str(node))

        return entities

    def _convert_relationships(
        self,
        relationships: list[Any],
        entities: list[ExtractedEntity],
        chunk_id: UUID,
        document_id: UUID,
    ) -> list[ExtractedRelationship]:
        """Convert LangChain relationships to ExtractedRelationship objects."""
        rels = []
        entity_names = {e.name.lower(): e for e in entities}

        for rel in relationships:
            try:
                # Map relationship type
                rel_type = self._map_relationship_type(rel.type)
                if rel_type is None:
                    continue

                source_name = rel.source.id
                target_name = rel.target.id

                # Verify entities exist
                if source_name.lower() not in entity_names:
                    continue
                if target_name.lower() not in entity_names:
                    continue

                relationship = ExtractedRelationship(
                    relationship_id=uuid4(),
                    source_entity=source_name,
                    target_entity=target_name,
                    relationship_type=rel_type,
                    confidence=0.85,  # LangChain doesn't provide confidence
                    evidence=[
                        EvidencePointer(
                            chunk_id=chunk_id,
                            document_id=document_id,
                            char_start=0,
                            char_end=0,
                            snippet=f"{source_name} {rel.type} {target_name}",
                        )
                    ],
                    metadata={
                        "document_id": str(document_id),
                        "langchain_type": rel.type,
                    },
                )
                rels.append(relationship)

            except Exception as e:
                logger.warning(
                    "Failed to convert relationship", error=str(e), rel=str(rel)
                )

        return rels

    def _map_node_type(self, langchain_type: str) -> EntityType | None:
        """Map LangChain node type to our EntityType enum."""
        type_map = {
            "scientificconcept": EntityType.SCIENTIFIC_CONCEPT,
            "scientific_concept": EntityType.SCIENTIFIC_CONCEPT,
            "concept": EntityType.SCIENTIFIC_CONCEPT,
            "method": EntityType.METHOD,
            "technique": EntityType.METHOD,
            "dataset": EntityType.DATASET,
            "data": EntityType.DATASET,
            "instrument": EntityType.INSTRUMENT,
            "detector": EntityType.INSTRUMENT,
            "sensor": EntityType.INSTRUMENT,
            "phenomenon": EntityType.PHENOMENON,
            "event": EntityType.PHENOMENON,
            "process": EntityType.PHENOMENON,
            "mission": EntityType.MISSION,
            "spacecraft": EntityType.SPACECRAFT,
            "satellite": EntityType.SPACECRAFT,
            "probe": EntityType.SPACECRAFT,
            "celestialbody": EntityType.CELESTIAL_BODY,
            "celestial_body": EntityType.CELESTIAL_BODY,
            "planet": EntityType.CELESTIAL_BODY,
            "star": EntityType.CELESTIAL_BODY,
            "sun": EntityType.CELESTIAL_BODY,
            "moon": EntityType.CELESTIAL_BODY,
            "organization": EntityType.ORGANIZATION,
            "institution": EntityType.ORGANIZATION,
            "agency": EntityType.ORGANIZATION,
            "person": EntityType.AUTHOR,
            "author": EntityType.AUTHOR,
            "researcher": EntityType.AUTHOR,
            "scientist": EntityType.AUTHOR,
        }
        return type_map.get(langchain_type.lower().replace(" ", ""))

    def _map_relationship_type(self, langchain_type: str) -> RelationshipType | None:
        """Map LangChain relationship type to our RelationshipType enum."""
        type_map = {
            "observes": RelationshipType.OBSERVES,
            "detects": RelationshipType.OBSERVES,
            "measures": RelationshipType.OBSERVES,
            "monitors": RelationshipType.OBSERVES,
            "part_of": RelationshipType.PART_OF,
            "component_of": RelationshipType.PART_OF,
            "belongs_to": RelationshipType.PART_OF,
            "causes": RelationshipType.CAUSES,
            "produces": RelationshipType.CAUSES,
            "leads_to": RelationshipType.CAUSES,
            "results_in": RelationshipType.CAUSES,
            "triggers": RelationshipType.CAUSES,
            "studies": RelationshipType.STUDIES,
            "analyzes": RelationshipType.STUDIES,
            "investigates": RelationshipType.STUDIES,
            "examines": RelationshipType.STUDIES,
            "related_to": RelationshipType.RELATED_TO,
            "associated_with": RelationshipType.RELATED_TO,
            "connected_to": RelationshipType.RELATED_TO,
            "describes": RelationshipType.RELATED_TO,
            "uses": RelationshipType.USES_INSTRUMENT,
            "uses_method": RelationshipType.USES_METHOD,
            "uses_instrument": RelationshipType.USES_INSTRUMENT,
            "uses_dataset": RelationshipType.USES_DATASET,
            "employs": RelationshipType.USES_METHOD,
            "operates": RelationshipType.USES_INSTRUMENT,
            "cites": RelationshipType.CITES,
            "references": RelationshipType.CITES,
            "mentions": RelationshipType.MENTIONS,
            "authored_by": RelationshipType.AUTHORED_BY,
            "written_by": RelationshipType.AUTHORED_BY,
            "created_by": RelationshipType.AUTHORED_BY,
            "orbits": RelationshipType.RELATED_TO,
            "occurs_at": RelationshipType.RELATED_TO,
            "built": RelationshipType.RELATED_TO,
            "contains": RelationshipType.PART_OF,
        }
        return type_map.get(langchain_type.lower().replace(" ", "_"))


class HybridExtractor:
    """Combines LangChain extraction with custom extraction for best results.

    Uses LangChain for initial extraction, then enhances with:
    - Custom entity normalization
    - Domain-specific relationship inference
    - Evidence snippet extraction
    """

    def __init__(self, settings: Settings):
        """Initialize the hybrid extractor."""
        self.settings = settings
        self.langchain_extractor = LangChainGraphExtractor(settings)

        # Import custom extractors for enhancement
        from .entity_extractor import EntityNormalizer
        self.normalizer = EntityNormalizer()

    async def extract(
        self,
        text: str,
        chunk_id: UUID,
        document_id: UUID,
    ) -> tuple[list[ExtractedEntity], list[ExtractedRelationship]]:
        """Extract using LangChain, then enhance with custom processing."""
        # Get base extraction from LangChain
        entities, relationships = await self.langchain_extractor.extract(
            text, chunk_id, document_id
        )

        # Normalize entities using our domain knowledge
        normalized_entities = [
            self.normalizer.normalize(e) for e in entities
        ]

        # Deduplicate
        final_entities = self.normalizer.deduplicate(normalized_entities)

        # Enhance relationships with evidence snippets
        enhanced_relationships = self._enhance_evidence(
            relationships, text, chunk_id, document_id
        )

        return final_entities, enhanced_relationships

    def _enhance_evidence(
        self,
        relationships: list[ExtractedRelationship],
        text: str,
        chunk_id: UUID,
        document_id: UUID,
    ) -> list[ExtractedRelationship]:
        """Enhance relationships with actual evidence from text."""
        for rel in relationships:
            # Find source and target in text
            source_pos = text.lower().find(rel.source_entity.lower())
            target_pos = text.lower().find(rel.target_entity.lower())

            if source_pos >= 0 and target_pos >= 0:
                # Extract snippet around the entities
                start = max(0, min(source_pos, target_pos) - 50)
                end = min(len(text), max(source_pos, target_pos) + 100)
                snippet = text[start:end].strip()

                if rel.evidence:
                    rel.evidence[0].snippet = snippet
                    rel.evidence[0].char_start = start
                    rel.evidence[0].char_end = end
                else:
                    rel.evidence = [
                        EvidencePointer(
                            chunk_id=chunk_id,
                            document_id=document_id,
                            char_start=start,
                            char_end=end,
                            snippet=snippet,
                        )
                    ]

        return relationships
