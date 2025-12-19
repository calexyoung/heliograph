"""Relationship extraction service using LLMs."""

import json
import re
from typing import Any
from uuid import UUID, uuid4

import httpx
import structlog

from ..config import Settings
from ..core.schemas import (
    EvidencePointer,
    ExtractedEntity,
    ExtractedRelationship,
    RelationshipType,
)

logger = structlog.get_logger()


# System prompt for relationship extraction
RELATIONSHIP_EXTRACTION_PROMPT = """You are an expert at extracting relationships between scientific entities in heliophysics and astrophysics research papers.

Given a text and a list of entities, extract relationships between them. Focus on:
- cites: One paper citing another
- authored_by: Paper authored by a person/team
- uses_method: Study using a specific method/technique
- uses_dataset: Study using a specific dataset
- uses_instrument: Study using a specific instrument
- studies: Research studying a phenomenon/concept
- mentions: Text mentioning an entity in context
- related_to: Semantic relationship between concepts
- part_of: Entity being part of another (e.g., instrument part of mission)
- causes: Causal relationship (e.g., solar flare causes geomagnetic storm)
- observes: Instrument/mission observing a phenomenon

For each relationship, provide:
1. source_entity: The name of the source entity
2. target_entity: The name of the target entity
3. relationship_type: One of [cites, authored_by, uses_method, uses_dataset, uses_instrument, studies, mentions, related_to, part_of, causes, observes]
4. confidence: A score from 0.0 to 1.0
5. evidence_snippet: The text that supports this relationship
6. char_start: Starting position of evidence in text
7. char_end: Ending position of evidence in text

Return a JSON array of relationships."""


class RelationshipExtractor:
    """Extracts relationships between entities using LLMs."""

    def __init__(self, settings: Settings):
        """Initialize the relationship extractor."""
        self.settings = settings
        self.http_client = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.http_client.aclose()

    async def extract_relationships(
        self,
        text: str,
        entities: list[ExtractedEntity],
        chunk_id: UUID,
        document_id: UUID,
    ) -> list[ExtractedRelationship]:
        """Extract relationships from text given entities.

        Args:
            text: The text to extract relationships from
            entities: List of entities found in the text
            chunk_id: The chunk ID this text belongs to
            document_id: The document ID

        Returns:
            List of extracted relationships
        """
        if not entities:
            return []

        # Create entity list for the prompt
        entity_list = [
            f"- {e.name} ({e.entity_type.value})" for e in entities
        ]
        entity_text = "\n".join(entity_list)

        if self.settings.EXTRACTION_PROVIDER == "openai":
            raw_rels = await self._extract_with_openai(text, entity_text)
        elif self.settings.EXTRACTION_PROVIDER == "anthropic":
            raw_rels = await self._extract_with_anthropic(text, entity_text)
        else:
            raw_rels = await self._extract_with_local(text, entities)

        # Convert to ExtractedRelationship objects
        relationships = []
        entity_names = {e.name.lower(): e for e in entities}

        for raw in raw_rels:
            try:
                rel_type = self._normalize_relationship_type(
                    raw.get("relationship_type", "")
                )
                if rel_type is None:
                    continue

                confidence = float(raw.get("confidence", 0.7))
                if confidence < self.settings.MIN_RELATIONSHIP_CONFIDENCE:
                    continue

                source_name = raw.get("source_entity", "")
                target_name = raw.get("target_entity", "")

                # Skip if entities not found
                if source_name.lower() not in entity_names:
                    continue
                if target_name.lower() not in entity_names:
                    continue

                # Create evidence pointer
                evidence = []
                snippet = raw.get("evidence_snippet", "")
                if snippet:
                    evidence.append(
                        EvidencePointer(
                            chunk_id=chunk_id,
                            document_id=document_id,
                            char_start=int(raw.get("char_start", 0)),
                            char_end=int(raw.get("char_end", len(snippet))),
                            snippet=snippet[:500],  # Limit snippet length
                        )
                    )

                relationship = ExtractedRelationship(
                    relationship_id=uuid4(),
                    source_entity=source_name,
                    target_entity=target_name,
                    relationship_type=rel_type,
                    confidence=confidence,
                    evidence=evidence,
                    metadata={"document_id": str(document_id)},
                )
                relationships.append(relationship)

            except (ValueError, KeyError) as e:
                logger.warning("Failed to parse relationship", error=str(e), raw=raw)
                continue

        # Limit relationships per chunk
        return relationships[: self.settings.MAX_RELATIONSHIPS_PER_CHUNK]

    async def _extract_with_openai(
        self, text: str, entity_text: str
    ) -> list[dict[str, Any]]:
        """Extract relationships using OpenAI API."""
        if not self.settings.OPENAI_API_KEY:
            logger.warning("OpenAI API key not set, returning empty relationships")
            return []

        try:
            response = await self.http_client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.settings.EXTRACTION_MODEL,
                    "messages": [
                        {"role": "system", "content": RELATIONSHIP_EXTRACTION_PROMPT},
                        {
                            "role": "user",
                            "content": f"Entities found:\n{entity_text}\n\nText:\n{text}",
                        },
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return parsed.get("relationships", []) if isinstance(parsed, dict) else parsed

        except Exception as e:
            logger.error("OpenAI relationship extraction failed", error=str(e))
            return []

    async def _extract_with_anthropic(
        self, text: str, entity_text: str
    ) -> list[dict[str, Any]]:
        """Extract relationships using Anthropic API."""
        if not self.settings.ANTHROPIC_API_KEY:
            logger.warning("Anthropic API key not set, returning empty relationships")
            return []

        try:
            response = await self.http_client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 4096,
                    "system": RELATIONSHIP_EXTRACTION_PROMPT,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Entities found:\n{entity_text}\n\nText:\n{text}\n\nReturn as JSON array.",
                        },
                    ],
                },
            )
            response.raise_for_status()
            result = response.json()
            content = result["content"][0]["text"]

            # Extract JSON from response
            json_match = re.search(r"\[[\s\S]*\]", content)
            if json_match:
                return json.loads(json_match.group())
            return []

        except Exception as e:
            logger.error("Anthropic relationship extraction failed", error=str(e))
            return []

    async def _extract_with_local(
        self, text: str, entities: list[ExtractedEntity]
    ) -> list[dict[str, Any]]:
        """Extract relationships using local patterns (fallback)."""
        relationships = []

        # Build entity map
        entity_positions = []
        for entity in entities:
            for mention in entity.mentions:
                entity_positions.append({
                    "entity": entity,
                    "start": mention.char_start,
                    "end": mention.char_end,
                })

        # Sort by position
        entity_positions.sort(key=lambda x: x["start"])

        # Find co-occurring entities (within 200 chars)
        for i, pos1 in enumerate(entity_positions):
            for j, pos2 in enumerate(entity_positions[i + 1 :], i + 1):
                distance = pos2["start"] - pos1["end"]
                if distance > 200:
                    break
                if distance < 0:
                    continue

                e1 = pos1["entity"]
                e2 = pos2["entity"]

                # Skip same entity type pairs for certain relationships
                if e1.canonical_name == e2.canonical_name:
                    continue

                # Determine relationship type based on entity types
                rel_type = self._infer_relationship_type(e1, e2, text, pos1, pos2)
                if rel_type is None:
                    continue

                snippet_start = max(0, pos1["start"] - 20)
                snippet_end = min(len(text), pos2["end"] + 20)
                snippet = text[snippet_start:snippet_end]

                relationships.append({
                    "source_entity": e1.name,
                    "target_entity": e2.name,
                    "relationship_type": rel_type.value,
                    "confidence": 0.7,
                    "evidence_snippet": snippet,
                    "char_start": pos1["start"],
                    "char_end": pos2["end"],
                })

        return relationships

    def _infer_relationship_type(
        self,
        e1: ExtractedEntity,
        e2: ExtractedEntity,
        text: str,
        pos1: dict,
        pos2: dict,
    ) -> RelationshipType | None:
        """Infer relationship type from entity types and context."""
        from ..core.schemas import EntityType

        t1 = e1.entity_type
        t2 = e2.entity_type

        # Get text between entities
        between = text[pos1["end"] : pos2["start"]].lower()

        # Check for explicit relationship words
        if "causes" in between or "caused by" in between or "results in" in between:
            return RelationshipType.CAUSES

        if "observes" in between or "observed" in between or "detected" in between:
            return RelationshipType.OBSERVES

        if "using" in between or "used" in between or "employed" in between:
            if t2 == EntityType.METHOD:
                return RelationshipType.USES_METHOD
            if t2 == EntityType.INSTRUMENT:
                return RelationshipType.USES_INSTRUMENT
            if t2 == EntityType.DATASET:
                return RelationshipType.USES_DATASET

        if "part of" in between or "component" in between:
            return RelationshipType.PART_OF

        if "studies" in between or "studied" in between or "investigates" in between:
            return RelationshipType.STUDIES

        # Default based on entity types
        if t1 == EntityType.MISSION and t2 == EntityType.INSTRUMENT:
            return RelationshipType.PART_OF

        if t1 == EntityType.PHENOMENON and t2 == EntityType.PHENOMENON:
            return RelationshipType.RELATED_TO

        if t2 == EntityType.AUTHOR:
            return RelationshipType.AUTHORED_BY

        return RelationshipType.MENTIONS

    def _normalize_relationship_type(self, type_str: str) -> RelationshipType | None:
        """Normalize relationship type string to enum."""
        type_map = {
            "cites": RelationshipType.CITES,
            "citation": RelationshipType.CITES,
            "authored_by": RelationshipType.AUTHORED_BY,
            "written_by": RelationshipType.AUTHORED_BY,
            "uses_method": RelationshipType.USES_METHOD,
            "uses_technique": RelationshipType.USES_METHOD,
            "employs_method": RelationshipType.USES_METHOD,
            "uses_dataset": RelationshipType.USES_DATASET,
            "uses_data": RelationshipType.USES_DATASET,
            "uses_instrument": RelationshipType.USES_INSTRUMENT,
            "uses_tool": RelationshipType.USES_INSTRUMENT,
            "studies": RelationshipType.STUDIES,
            "investigates": RelationshipType.STUDIES,
            "examines": RelationshipType.STUDIES,
            "mentions": RelationshipType.MENTIONS,
            "references": RelationshipType.MENTIONS,
            "related_to": RelationshipType.RELATED_TO,
            "associated_with": RelationshipType.RELATED_TO,
            "part_of": RelationshipType.PART_OF,
            "component_of": RelationshipType.PART_OF,
            "causes": RelationshipType.CAUSES,
            "leads_to": RelationshipType.CAUSES,
            "results_in": RelationshipType.CAUSES,
            "observes": RelationshipType.OBSERVES,
            "detects": RelationshipType.OBSERVES,
            "measures": RelationshipType.OBSERVES,
        }
        return type_map.get(type_str.lower())
