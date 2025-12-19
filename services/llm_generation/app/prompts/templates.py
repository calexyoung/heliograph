"""Prompt templates for RAG generation."""

from ..core.schemas import CitationInfo


# System prompt for strict citation mode
SYSTEM_PROMPT_STRICT = """You are a scientific research assistant specializing in heliophysics and astrophysics. Your role is to answer questions based ONLY on the provided context from research papers.

CRITICAL RULES:
1. You MUST cite sources for every factual claim using [N] notation where N is the citation number
2. If the context doesn't contain enough information to answer the question, say "I don't have sufficient information in the provided sources to answer this question."
3. NEVER make up information or cite sources that weren't provided
4. Be precise and scientific in your language
5. When multiple sources support a claim, cite all of them [1][2]
6. Distinguish between established facts and interpretations/hypotheses from the papers

FORMAT:
- Use inline citations [N] immediately after the relevant claim
- At the end, you may summarize which sources were most relevant
- Keep responses focused and concise while being thorough
"""

# System prompt for relaxed citation mode
SYSTEM_PROMPT_RELAXED = """You are a scientific research assistant specializing in heliophysics and astrophysics. Your role is to answer questions based on the provided context from research papers.

GUIDELINES:
1. Use the provided context as your primary source of information
2. Cite sources using [N] notation when making specific claims
3. You may synthesize information across sources
4. If context is insufficient, you may provide general knowledge with a caveat
5. Be helpful while maintaining scientific accuracy

FORMAT:
- Use inline citations [N] for specific claims from the context
- Clearly distinguish between information from sources and general knowledge
"""

# Intent-specific prompts
INTENT_PROMPTS = {
    "summary": "Provide a comprehensive summary of what the sources say about this topic.",
    "compare": "Compare and contrast the different perspectives or findings from the sources.",
    "find_evidence": "Identify and present the evidence from the sources that supports or refutes the claim.",
    "explore": "Explore the connections and related concepts mentioned in the sources.",
    "explain": "Explain the concept or mechanism based on the information in the sources.",
    "list": "List the relevant items found in the sources.",
    "factual": "Answer the question directly based on the facts in the sources.",
}


def build_system_prompt(citation_mode: str = "strict", intent: str | None = None) -> str:
    """Build the system prompt based on mode and intent.

    Args:
        citation_mode: "strict" or "relaxed"
        intent: Optional query intent

    Returns:
        System prompt string
    """
    base_prompt = SYSTEM_PROMPT_STRICT if citation_mode == "strict" else SYSTEM_PROMPT_RELAXED

    if intent and intent in INTENT_PROMPTS:
        return f"{base_prompt}\n\nFor this query, {INTENT_PROMPTS[intent]}"

    return base_prompt


def build_user_prompt(
    query: str,
    context: str,
    citations: list[CitationInfo],
) -> str:
    """Build the user prompt with context and query.

    Args:
        query: The user's question
        context: The assembled context from retrieval
        citations: List of citation information

    Returns:
        User prompt string
    """
    # Build citation reference section
    citation_refs = []
    for cit in citations:
        ref_parts = [f"[{cit.citation_id}]"]
        if cit.title:
            ref_parts.append(cit.title)
        if cit.authors:
            ref_parts.append(f"by {', '.join(cit.authors[:3])}")
            if len(cit.authors) > 3:
                ref_parts.append("et al.")
        if cit.year:
            ref_parts.append(f"({cit.year})")
        citation_refs.append(" ".join(ref_parts))

    citation_list = "\n".join(citation_refs)

    prompt = f"""AVAILABLE SOURCES:
{citation_list}

CONTEXT FROM SOURCES:
{context}

USER QUESTION:
{query}

Please answer the question based on the provided context. Remember to cite your sources using [N] notation."""

    return prompt


def build_conversation_prompt(
    context: str | None,
    citations: list[CitationInfo],
) -> str:
    """Build context prompt for conversation mode.

    Args:
        context: Optional context from retrieval
        citations: List of citations

    Returns:
        Context prompt to prepend to conversation
    """
    if not context and not citations:
        return ""

    parts = []

    if citations:
        citation_refs = []
        for cit in citations:
            ref = f"[{cit.citation_id}] {cit.title}"
            if cit.year:
                ref += f" ({cit.year})"
            citation_refs.append(ref)
        parts.append("Available sources:\n" + "\n".join(citation_refs))

    if context:
        parts.append(f"Context from sources:\n{context}")

    return "\n\n".join(parts)


# Prompt injection defense patterns
INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|above)\s+instructions",
    r"disregard\s+(previous|all|above)",
    r"forget\s+(everything|all|previous)",
    r"new\s+instructions?:",
    r"system\s*:\s*",
    r"<\|im_start\|>",
    r"\[INST\]",
]


def sanitize_input(text: str) -> str:
    """Sanitize input to prevent prompt injection.

    Args:
        text: Input text to sanitize

    Returns:
        Sanitized text
    """
    import re

    sanitized = text

    # Remove potential injection patterns
    for pattern in INJECTION_PATTERNS:
        sanitized = re.sub(pattern, "[FILTERED]", sanitized, flags=re.IGNORECASE)

    # Remove special tokens that might be interpreted
    sanitized = sanitized.replace("<|", "< |").replace("|>", "| >")

    return sanitized
