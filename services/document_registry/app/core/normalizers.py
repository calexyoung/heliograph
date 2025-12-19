"""Text normalization functions for deduplication."""

import re
import unicodedata


def normalize_title(title: str) -> str:
    """Normalize a title for comparison.

    Normalization steps:
    1. Unicode normalization (NFD to decompose)
    2. Remove combining characters (accents)
    3. Convert to lowercase
    4. Remove punctuation except alphanumeric and spaces
    5. Collapse multiple whitespace to single space
    6. Strip leading/trailing whitespace

    Args:
        title: Raw title string

    Returns:
        Normalized title string
    """
    if not title:
        return ""

    # Unicode NFD normalization (decomposes characters)
    normalized = unicodedata.normalize("NFD", title)

    # Remove combining characters (accents, diacritics)
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Mn")

    # Lowercase
    normalized = normalized.lower()

    # Remove punctuation (keep only alphanumeric, spaces, and basic dashes)
    normalized = re.sub(r"[^\w\s-]", "", normalized)

    # Replace dashes and underscores with spaces
    normalized = re.sub(r"[-_]+", " ", normalized)

    # Collapse whitespace
    normalized = re.sub(r"\s+", " ", normalized)

    # Strip
    return normalized.strip()


def normalize_doi(doi: str | None) -> str | None:
    """Normalize a DOI for comparison.

    Normalization steps:
    1. Remove common URL prefixes (https://doi.org/, http://dx.doi.org/)
    2. Convert to lowercase
    3. Strip whitespace

    Args:
        doi: Raw DOI string or None

    Returns:
        Normalized DOI string or None
    """
    if not doi:
        return None

    normalized = doi.strip()

    # Remove common URL prefixes
    prefixes = [
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
        "DOI:",
    ]

    for prefix in prefixes:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break

    # Lowercase (DOIs are case-insensitive)
    normalized = normalized.lower()

    return normalized.strip()


def normalize_author_name(name: str) -> str:
    """Normalize an author name for comparison.

    Args:
        name: Raw author name

    Returns:
        Normalized author name
    """
    if not name:
        return ""

    # Unicode normalization
    normalized = unicodedata.normalize("NFKC", name)

    # Lowercase
    normalized = normalized.lower()

    # Remove punctuation except letters and spaces
    normalized = re.sub(r"[^\w\s]", "", normalized)

    # Collapse whitespace
    normalized = re.sub(r"\s+", " ", normalized)

    return normalized.strip()
