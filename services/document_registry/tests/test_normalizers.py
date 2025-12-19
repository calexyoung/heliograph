"""Tests for text normalization functions."""

import pytest

from services.document_registry.app.core.normalizers import (
    normalize_author_name,
    normalize_doi,
    normalize_title,
)


class TestNormalizeTitle:
    """Tests for title normalization."""

    def test_basic_normalization(self):
        """Test basic title normalization."""
        title = "A Study of Solar Flares"
        result = normalize_title(title)
        assert result == "a study of solar flares"

    def test_removes_punctuation(self):
        """Test that punctuation is removed."""
        title = "Solar Flares: A Comprehensive Study!"
        result = normalize_title(title)
        assert result == "solar flares a comprehensive study"

    def test_collapses_whitespace(self):
        """Test that multiple spaces are collapsed."""
        title = "Solar   Flares    Study"
        result = normalize_title(title)
        assert result == "solar flares study"

    def test_handles_unicode(self):
        """Test Unicode normalization."""
        title = "Magnétic Field Analysïs"
        result = normalize_title(title)
        assert "magnetic" in result.lower()

    def test_handles_dashes(self):
        """Test that dashes are converted to spaces."""
        title = "Solar-Terrestrial Connections"
        result = normalize_title(title)
        assert result == "solar terrestrial connections"

    def test_empty_string(self):
        """Test empty string handling."""
        assert normalize_title("") == ""

    def test_strips_whitespace(self):
        """Test leading/trailing whitespace is stripped."""
        title = "  Solar Flares  "
        result = normalize_title(title)
        assert result == "solar flares"


class TestNormalizeDoi:
    """Tests for DOI normalization."""

    def test_basic_doi(self):
        """Test basic DOI without prefix."""
        doi = "10.1234/test.2024.001"
        result = normalize_doi(doi)
        assert result == "10.1234/test.2024.001"

    def test_removes_https_prefix(self):
        """Test removal of https://doi.org/ prefix."""
        doi = "https://doi.org/10.1234/test.2024.001"
        result = normalize_doi(doi)
        assert result == "10.1234/test.2024.001"

    def test_removes_http_prefix(self):
        """Test removal of http://doi.org/ prefix."""
        doi = "http://doi.org/10.1234/test.2024.001"
        result = normalize_doi(doi)
        assert result == "10.1234/test.2024.001"

    def test_removes_dx_doi_prefix(self):
        """Test removal of dx.doi.org prefix."""
        doi = "https://dx.doi.org/10.1234/test.2024.001"
        result = normalize_doi(doi)
        assert result == "10.1234/test.2024.001"

    def test_removes_doi_prefix(self):
        """Test removal of doi: prefix."""
        doi = "doi:10.1234/test.2024.001"
        result = normalize_doi(doi)
        assert result == "10.1234/test.2024.001"

    def test_lowercase(self):
        """Test DOI is lowercased."""
        doi = "10.1234/TEST.2024.001"
        result = normalize_doi(doi)
        assert result == "10.1234/test.2024.001"

    def test_none_input(self):
        """Test None input returns None."""
        assert normalize_doi(None) is None

    def test_empty_string(self):
        """Test empty string returns None."""
        assert normalize_doi("") is None

    def test_strips_whitespace(self):
        """Test leading/trailing whitespace is stripped."""
        doi = "  10.1234/test.2024.001  "
        result = normalize_doi(doi)
        assert result == "10.1234/test.2024.001"


class TestNormalizeAuthorName:
    """Tests for author name normalization."""

    def test_basic_name(self):
        """Test basic name normalization."""
        name = "John Doe"
        result = normalize_author_name(name)
        assert result == "john doe"

    def test_removes_punctuation(self):
        """Test punctuation removal."""
        name = "O'Connor, Mary-Jane"
        result = normalize_author_name(name)
        assert result == "oconnor maryjane"

    def test_collapses_whitespace(self):
        """Test whitespace collapsing."""
        name = "John   Middle   Doe"
        result = normalize_author_name(name)
        assert result == "john middle doe"

    def test_empty_string(self):
        """Test empty string handling."""
        assert normalize_author_name("") == ""
