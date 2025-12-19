"""Query understanding and parsing module."""

import re
from typing import Any

import structlog

from ..config import Settings
from .schemas import ParsedQuery, QueryConstraint, QueryIntent

logger = structlog.get_logger()


class QueryParser:
    """Parses and analyzes user queries."""

    def __init__(self, settings: Settings):
        """Initialize the query parser."""
        self.settings = settings

        # Intent patterns
        self.intent_patterns = {
            QueryIntent.SUMMARY: [
                r"summarize",
                r"summary of",
                r"overview of",
                r"what is known about",
                r"tell me about",
            ],
            QueryIntent.COMPARE: [
                r"compare",
                r"difference between",
                r"how does .+ differ from",
                r"vs\.?",
                r"versus",
                r"similarities between",
            ],
            QueryIntent.FIND_EVIDENCE: [
                r"evidence for",
                r"evidence that",
                r"support for",
                r"prove",
                r"show that",
                r"demonstrate",
            ],
            QueryIntent.EXPLORE: [
                r"related to",
                r"connections? between",
                r"explore",
                r"what else",
                r"associated with",
            ],
            QueryIntent.EXPLAIN: [
                r"explain",
                r"how does",
                r"why does",
                r"what causes",
                r"mechanism of",
                r"how is .+ related",
            ],
            QueryIntent.LIST: [
                r"list",
                r"what are the",
                r"which .+ are",
                r"enumerate",
                r"name the",
            ],
            QueryIntent.FACTUAL: [
                r"what is",
                r"when did",
                r"who",
                r"where",
                r"how many",
                r"how much",
            ],
        }

        # Constraint patterns
        self.year_pattern = re.compile(
            r"(?:from|after|since|between)\s+(\d{4})(?:\s+(?:to|and|until)\s+(\d{4}))?|"
            r"(?:before|until|up to)\s+(\d{4})|"
            r"in\s+(\d{4})"
        )
        self.author_pattern = re.compile(
            r"(?:by|author(?:ed by)?)\s+([A-Z][a-z]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][a-z]+))?)"
        )

    def parse(self, query: str) -> ParsedQuery:
        """Parse a query into structured form.

        Args:
            query: The user's query string

        Returns:
            ParsedQuery with intent, entities, constraints, etc.
        """
        # Detect intent
        intent = self._detect_intent(query)

        # Extract constraints
        constraints = self._extract_constraints(query)

        # Extract entities (simple keyword extraction for now)
        entities = self._extract_entities(query)

        # Extract keywords
        keywords = self._extract_keywords(query)

        # Rewrite query if enabled
        rewritten = None
        if self.settings.QUERY_EXPANSION_ENABLED:
            rewritten = self._rewrite_query(query, entities)

        return ParsedQuery(
            original_query=query,
            intent=intent,
            rewritten_query=rewritten,
            entities=entities,
            constraints=constraints,
            keywords=keywords,
        )

    def _detect_intent(self, query: str) -> QueryIntent:
        """Detect the intent of the query."""
        query_lower = query.lower()

        for intent, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    return intent

        # Default to factual for simple queries
        return QueryIntent.FACTUAL

    def _extract_constraints(self, query: str) -> QueryConstraint:
        """Extract constraints from the query."""
        constraint = QueryConstraint()

        # Extract year constraints
        year_match = self.year_pattern.search(query)
        if year_match:
            groups = year_match.groups()
            if groups[0]:  # "from X to Y" or "from X"
                constraint.year_start = int(groups[0])
                if groups[1]:
                    constraint.year_end = int(groups[1])
            elif groups[2]:  # "before X"
                constraint.year_end = int(groups[2])
            elif groups[3]:  # "in X"
                constraint.year_start = int(groups[3])
                constraint.year_end = int(groups[3])

        # Extract author constraints
        author_match = self.author_pattern.search(query)
        if author_match:
            constraint.authors = [author_match.group(1)]

        return constraint

    def _extract_entities(self, query: str) -> list[str]:
        """Extract scientific entities from the query."""
        entities = []

        # Known entity patterns for heliophysics
        entity_patterns = [
            r"solar\s+wind",
            r"coronal\s+mass\s+ejection",
            r"CME",
            r"magnetic\s+reconnection",
            r"geomagnetic\s+storm",
            r"solar\s+flare",
            r"magnetosphere",
            r"ionosphere",
            r"heliosphere",
            r"Parker\s+Solar\s+Probe",
            r"Solar\s+Orbiter",
            r"SDO",
            r"STEREO",
            r"Van\s+Allen\s+(?:belt|probe)s?",
            r"radiation\s+belt",
            r"bow\s+shock",
            r"magnetopause",
            r"plasmasphere",
            r"aurora(?:l)?",
            r"substorm",
            r"ring\s+current",
        ]

        for pattern in entity_patterns:
            matches = re.findall(pattern, query, re.IGNORECASE)
            entities.extend(matches)

        return list(set(entities))

    def _extract_keywords(self, query: str) -> list[str]:
        """Extract important keywords from the query."""
        # Remove common stopwords and constraint words
        stopwords = {
            "a", "an", "the", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "can",
            "about", "above", "after", "again", "against", "all", "am",
            "and", "any", "as", "at", "because", "before", "below",
            "between", "both", "but", "by", "for", "from", "further",
            "here", "how", "if", "in", "into", "it", "its", "itself",
            "just", "more", "most", "no", "nor", "not", "of", "off",
            "on", "once", "only", "or", "other", "our", "out", "over",
            "own", "same", "so", "some", "such", "than", "that", "their",
            "them", "then", "there", "these", "they", "this", "those",
            "through", "to", "too", "under", "until", "up", "very",
            "what", "when", "where", "which", "while", "who", "why",
            "with", "you", "your", "compare", "explain", "list", "find",
            "show", "tell", "me", "please", "summarize", "describe",
        }

        # Tokenize and filter
        words = re.findall(r"\b[a-zA-Z]{3,}\b", query.lower())
        keywords = [w for w in words if w not in stopwords]

        return keywords

    def _rewrite_query(self, query: str, entities: list[str]) -> str:
        """Rewrite query for better retrieval.

        Generates an enhanced query that improves semantic matching
        by adding related terms and removing question words.
        """
        # Simple expansion: add entity variations (heliophysics-specific)
        expansions = {
            "cme": "coronal mass ejection CME",
            "sw": "solar wind",
            "imf": "interplanetary magnetic field IMF",
            "psp": "Parker Solar Probe PSP",
            "sdo": "Solar Dynamics Observatory SDO",
        }

        rewritten = query
        for abbrev, expansion in expansions.items():
            if re.search(rf"\b{abbrev}\b", query, re.IGNORECASE):
                rewritten = f"{rewritten} {expansion}"

        # Remove question prefixes for better embedding matching
        question_prefixes = [
            r"^what is (the )?",
            r"^how (do|does|is|are|can) ",
            r"^why (do|does|is|are) ",
            r"^explain (what|how|why) ",
            r"^tell me about ",
            r"^describe ",
            r"^can you (explain|tell|describe) ",
        ]

        cleaned = rewritten.lower()
        for prefix in question_prefixes:
            cleaned = re.sub(prefix, "", cleaned, flags=re.IGNORECASE)

        # Keep original and add cleaned version for hybrid matching
        if cleaned != rewritten.lower():
            rewritten = f"{rewritten} {cleaned}"

        return rewritten

    def generate_query_variations(self, query: str) -> list[str]:
        """Generate multiple query variations for fusion retrieval.

        Args:
            query: Original query string

        Returns:
            List of query variations to search with
        """
        variations = [query]

        # Add lowercase version
        lower = query.lower()
        if lower != query:
            variations.append(lower)

        # Generate question-stripped version
        stripped = re.sub(
            r"^(what|how|why|when|where|who|which|can you|please|explain|describe|tell me) (is|are|do|does|was|were|about|the)?\s*",
            "",
            lower,
            flags=re.IGNORECASE
        ).strip()

        if stripped and stripped != lower and len(stripped) > 10:
            variations.append(stripped)

        # Add version with "and" replaced by separate terms
        if " and " in lower:
            parts = lower.split(" and ")
            if len(parts) == 2 and len(parts[0]) > 5 and len(parts[1]) > 5:
                variations.extend(parts)

        return list(dict.fromkeys(variations))  # Remove duplicates while preserving order


class QueryExpander:
    """Expands queries using synonyms and related terms."""

    def __init__(self):
        """Initialize with domain-specific expansions."""
        self.expansions = {
            "solar wind": ["SW", "interplanetary medium", "solar plasma"],
            "coronal mass ejection": ["CME", "solar eruption", "plasma ejection"],
            "geomagnetic storm": ["magnetic storm", "space weather event"],
            "magnetic reconnection": ["reconnection event", "field line merging"],
            "magnetosphere": ["Earth's magnetic field", "geospace"],
            "aurora": ["northern lights", "southern lights", "auroral emission"],
        }

    def expand(self, query: str) -> list[str]:
        """Expand query with related terms.

        Args:
            query: Original query

        Returns:
            List of expanded query variations
        """
        variations = [query]

        for term, synonyms in self.expansions.items():
            if term.lower() in query.lower():
                for syn in synonyms:
                    variation = re.sub(
                        rf"\b{re.escape(term)}\b",
                        syn,
                        query,
                        flags=re.IGNORECASE,
                    )
                    if variation not in variations:
                        variations.append(variation)

        return variations
