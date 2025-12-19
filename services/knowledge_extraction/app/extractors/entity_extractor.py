"""Entity extraction service using LLMs.

Supports two modes:
1. LiteLLM unified client (recommended) - Single interface for all providers
2. Legacy direct HTTP calls - Separate OpenAI/Anthropic implementations

Set USE_LITELLM=true in settings to use the unified client.
"""

import json
import re
from typing import Any
from uuid import UUID, uuid4

import httpx
import structlog

from ..config import Settings
from ..core.schemas import EntityMention, EntityType, ExtractedEntity

logger = structlog.get_logger()

# Try to import LiteLLM
try:
    import litellm

    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    litellm = None


# System prompt for entity extraction
ENTITY_EXTRACTION_PROMPT = """You are an expert scientific entity extractor for heliophysics and astrophysics research papers.

Extract named entities from the provided text. Focus on:
- Scientific concepts (e.g., "solar wind", "magnetic reconnection", "coronal mass ejection")
- Methods and techniques (e.g., "spectroscopic analysis", "Monte Carlo simulation")
- Datasets (e.g., "OMNI dataset", "ACE solar wind data")
- Instruments (e.g., "Solar Dynamics Observatory", "STEREO coronagraph")
- Phenomena (e.g., "geomagnetic storm", "solar flare", "aurora")
- Missions (e.g., "Parker Solar Probe", "Solar Orbiter")
- Spacecraft (e.g., "Voyager 1", "Wind spacecraft")
- Celestial bodies (e.g., "Sun", "Earth's magnetosphere", "Jupiter")
- Organizations (e.g., "NASA", "ESA", "NOAA")

For each entity, provide:
1. name: The exact text as it appears
2. canonical_name: A normalized/standard form of the entity
3. entity_type: One of [scientific_concept, method, dataset, instrument, phenomenon, mission, spacecraft, celestial_body, organization]
4. confidence: A score from 0.0 to 1.0 indicating confidence
5. char_start: Starting character position in the text
6. char_end: Ending character position in the text

Return a JSON array of entities. Be precise with character positions."""


class EntityExtractor:
    """Extracts entities from document chunks using LLMs.

    Uses LiteLLM when available for unified provider access,
    otherwise falls back to direct HTTP calls.
    """

    def __init__(self, settings: Settings):
        """Initialize the entity extractor."""
        self.settings = settings
        self.http_client = httpx.AsyncClient(timeout=60.0)
        self._use_litellm = (
            getattr(settings, "USE_LITELLM", True) and LITELLM_AVAILABLE
        )

        if self._use_litellm:
            self._configure_litellm()

    def _configure_litellm(self) -> None:
        """Configure LiteLLM with API keys."""
        import os

        if self.settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = self.settings.OPENAI_API_KEY
        if self.settings.ANTHROPIC_API_KEY:
            os.environ["ANTHROPIC_API_KEY"] = self.settings.ANTHROPIC_API_KEY

        litellm.drop_params = True

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.http_client.aclose()

    async def _extract_with_litellm(self, text: str) -> list[dict[str, Any]]:
        """Extract entities using LiteLLM unified client.

        This method works with any provider supported by LiteLLM.
        """
        # Determine model based on provider setting
        provider = self.settings.EXTRACTION_PROVIDER
        if provider == "anthropic":
            model = f"anthropic/{self.settings.EXTRACTION_MODEL}"
        elif provider == "local":
            model = f"ollama/{self.settings.LOCAL_MODEL_NAME}"
        else:
            model = self.settings.EXTRACTION_MODEL  # OpenAI (no prefix)

        try:
            logger.debug(
                "litellm_entity_extraction",
                model=model,
                text_length=len(text),
            )

            response = await litellm.acompletion(
                model=model,
                messages=[
                    {"role": "system", "content": ENTITY_EXTRACTION_PROMPT},
                    {
                        "role": "user",
                        "content": f"Extract entities from the following text:\n\n{text}",
                    },
                ],
                temperature=0.1,
                response_format={"type": "json_object"} if provider == "openai" else None,
            )

            content = response.choices[0].message.content

            # Parse JSON response
            try:
                parsed = json.loads(content)
                return parsed.get("entities", []) if isinstance(parsed, dict) else parsed
            except json.JSONDecodeError:
                # Try to extract JSON array from response
                json_match = re.search(r"\[[\s\S]*\]", content)
                if json_match:
                    return json.loads(json_match.group())
                return []

        except Exception as e:
            logger.error(
                "litellm_entity_extraction_failed",
                model=model,
                error=str(e),
            )
            # Fall back to local pattern extraction
            return await self._extract_with_local(text)

    async def extract_entities(
        self,
        text: str,
        chunk_id: UUID,
        document_id: UUID,
    ) -> list[ExtractedEntity]:
        """Extract entities from text.

        Args:
            text: The text to extract entities from
            chunk_id: The chunk ID this text belongs to
            document_id: The document ID

        Returns:
            List of extracted entities
        """
        # Use LiteLLM if available
        if self._use_litellm:
            raw_entities = await self._extract_with_litellm(text)
        elif self.settings.EXTRACTION_PROVIDER == "openai":
            raw_entities = await self._extract_with_openai(text)
        elif self.settings.EXTRACTION_PROVIDER == "anthropic":
            raw_entities = await self._extract_with_anthropic(text)
        else:
            raw_entities = await self._extract_with_local(text)

        # Convert to ExtractedEntity objects
        entities = []
        for raw in raw_entities:
            try:
                entity_type = self._normalize_entity_type(raw.get("entity_type", ""))
                if entity_type is None:
                    continue

                confidence = float(raw.get("confidence", 0.8))
                if confidence < self.settings.MIN_ENTITY_CONFIDENCE:
                    continue

                mention = EntityMention(
                    chunk_id=chunk_id,
                    text=raw.get("name", ""),
                    char_start=int(raw.get("char_start", 0)),
                    char_end=int(raw.get("char_end", 0)),
                    confidence=confidence,
                )

                entity = ExtractedEntity(
                    entity_id=uuid4(),
                    name=raw.get("name", ""),
                    canonical_name=raw.get("canonical_name", raw.get("name", "")).lower(),
                    entity_type=entity_type,
                    confidence=confidence,
                    aliases=[],
                    mentions=[mention],
                    metadata={"document_id": str(document_id)},
                )
                entities.append(entity)

            except (ValueError, KeyError) as e:
                logger.warning("Failed to parse entity", error=str(e), raw=raw)
                continue

        # Limit entities per chunk
        return entities[: self.settings.MAX_ENTITIES_PER_CHUNK]

    async def _extract_with_openai(self, text: str) -> list[dict[str, Any]]:
        """Extract entities using OpenAI API."""
        if not self.settings.OPENAI_API_KEY:
            logger.warning("OpenAI API key not set, returning empty entities")
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
                        {"role": "system", "content": ENTITY_EXTRACTION_PROMPT},
                        {
                            "role": "user",
                            "content": f"Extract entities from the following text:\n\n{text}",
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
            return parsed.get("entities", []) if isinstance(parsed, dict) else parsed

        except Exception as e:
            logger.error("OpenAI entity extraction failed", error=str(e))
            return []

    async def _extract_with_anthropic(self, text: str) -> list[dict[str, Any]]:
        """Extract entities using Anthropic API."""
        if not self.settings.ANTHROPIC_API_KEY:
            logger.warning("Anthropic API key not set, returning empty entities")
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
                    "system": ENTITY_EXTRACTION_PROMPT,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Extract entities from the following text and return as JSON array:\n\n{text}",
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
            logger.error("Anthropic entity extraction failed", error=str(e))
            return []

    async def _extract_with_local(self, text: str) -> list[dict[str, Any]]:
        """Extract entities using local patterns (fallback)."""
        # Simple pattern-based extraction as fallback
        entities = []

        # Scientific concepts patterns
        concept_patterns = [
            r"solar\s+wind",
            r"magnetic\s+reconnection",
            r"coronal\s+mass\s+ejection",
            r"geomagnetic\s+storm",
            r"solar\s+flare",
            r"magnetosphere",
            r"ionosphere",
            r"heliosphere",
            r"plasma\s+sheet",
            r"bow\s+shock",
        ]

        for pattern in concept_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                entities.append({
                    "name": match.group(),
                    "canonical_name": match.group().lower(),
                    "entity_type": "scientific_concept",
                    "confidence": 0.85,
                    "char_start": match.start(),
                    "char_end": match.end(),
                })

        # Mission/spacecraft patterns
        mission_patterns = [
            r"Parker\s+Solar\s+Probe",
            r"Solar\s+Orbiter",
            r"SDO",
            r"STEREO",
            r"ACE",
            r"Wind\s+spacecraft",
            r"Voyager\s+\d",
            r"MMS",
            r"Van\s+Allen\s+Probes",
        ]

        for pattern in mission_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                entities.append({
                    "name": match.group(),
                    "canonical_name": match.group(),
                    "entity_type": "mission",
                    "confidence": 0.9,
                    "char_start": match.start(),
                    "char_end": match.end(),
                })

        return entities

    def _normalize_entity_type(self, type_str: str) -> EntityType | None:
        """Normalize entity type string to enum."""
        type_map = {
            "scientific_concept": EntityType.SCIENTIFIC_CONCEPT,
            "concept": EntityType.SCIENTIFIC_CONCEPT,
            "method": EntityType.METHOD,
            "technique": EntityType.METHOD,
            "dataset": EntityType.DATASET,
            "data": EntityType.DATASET,
            "instrument": EntityType.INSTRUMENT,
            "phenomenon": EntityType.PHENOMENON,
            "event": EntityType.PHENOMENON,
            "mission": EntityType.MISSION,
            "spacecraft": EntityType.SPACECRAFT,
            "satellite": EntityType.SPACECRAFT,
            "celestial_body": EntityType.CELESTIAL_BODY,
            "body": EntityType.CELESTIAL_BODY,
            "planet": EntityType.CELESTIAL_BODY,
            "star": EntityType.CELESTIAL_BODY,
            "organization": EntityType.ORGANIZATION,
            "institution": EntityType.ORGANIZATION,
            "author": EntityType.AUTHOR,
            "person": EntityType.AUTHOR,
        }
        return type_map.get(type_str.lower())


class EntityNormalizer:
    """Normalizes and deduplicates entities."""

    def __init__(self):
        """Initialize normalizer with known canonical forms."""
        self.canonical_forms: dict[str, str] = {
            "cme": "coronal mass ejection",
            "cmes": "coronal mass ejection",
            "sw": "solar wind",
            "imf": "interplanetary magnetic field",
            "dst": "disturbance storm time index",
            "kp": "kp index",
            "psp": "parker solar probe",
            "sdo": "solar dynamics observatory",
            "stereo": "solar terrestrial relations observatory",
            "ace": "advanced composition explorer",
            "mms": "magnetospheric multiscale mission",
        }

    def normalize(self, entity: ExtractedEntity) -> ExtractedEntity:
        """Normalize an entity to its canonical form."""
        lower_name = entity.name.lower().strip()

        # Check if we have a known canonical form
        if lower_name in self.canonical_forms:
            canonical = self.canonical_forms[lower_name]
            if lower_name != canonical:
                entity.aliases.append(entity.name)
            entity.canonical_name = canonical
        else:
            entity.canonical_name = lower_name

        return entity

    def deduplicate(self, entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
        """Deduplicate entities by canonical name and type."""
        seen: dict[tuple[str, EntityType], ExtractedEntity] = {}

        for entity in entities:
            key = (entity.canonical_name, entity.entity_type)

            if key in seen:
                # Merge mentions and aliases
                existing = seen[key]
                existing.mentions.extend(entity.mentions)
                for alias in entity.aliases:
                    if alias not in existing.aliases:
                        existing.aliases.append(alias)
                if entity.name not in existing.aliases and entity.name != existing.name:
                    existing.aliases.append(entity.name)
                # Keep higher confidence
                existing.confidence = max(existing.confidence, entity.confidence)
            else:
                seen[key] = entity

        return list(seen.values())
