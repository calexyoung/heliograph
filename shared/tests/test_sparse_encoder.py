"""Tests for sparse vector encoder (BM25-style keyword search)."""

import math

import pytest

from shared.utils.sparse_encoder import (
    SparseEncoder,
    get_sparse_encoder,
    set_sparse_encoder,
    _global_encoder,
)


class TestSparseEncoderInit:
    """Tests for SparseEncoder initialization."""

    def test_init_defaults(self):
        """Test initialization with default values."""
        encoder = SparseEncoder()
        assert encoder.vocab == {}
        assert encoder.idf_scores == {}
        assert encoder.avg_doc_length == 200.0
        assert encoder._next_idx == 0

    def test_init_with_vocab(self):
        """Test initialization with existing vocabulary."""
        vocab = {"solar": 0, "flare": 1, "corona": 2}
        encoder = SparseEncoder(vocab=vocab)
        assert encoder.vocab == vocab
        assert encoder._next_idx == 3  # max index + 1

    def test_init_with_idf_scores(self):
        """Test initialization with pre-computed IDF scores."""
        idf_scores = {"solar": 1.5, "flare": 2.0}
        encoder = SparseEncoder(idf_scores=idf_scores)
        assert encoder.idf_scores == idf_scores

    def test_init_with_avg_doc_length(self):
        """Test initialization with custom average document length."""
        encoder = SparseEncoder(avg_doc_length=500.0)
        assert encoder.avg_doc_length == 500.0

    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        vocab = {"term1": 0, "term2": 5}
        idf_scores = {"term1": 1.2, "term2": 0.8}
        encoder = SparseEncoder(
            vocab=vocab,
            idf_scores=idf_scores,
            avg_doc_length=150.0,
        )
        assert encoder.vocab == vocab
        assert encoder.idf_scores == idf_scores
        assert encoder.avg_doc_length == 150.0
        assert encoder._next_idx == 6  # max(0, 5) + 1


class TestSparseEncoderTokenize:
    """Tests for SparseEncoder.tokenize."""

    @pytest.fixture
    def encoder(self):
        """Create a SparseEncoder for testing."""
        return SparseEncoder()

    def test_tokenize_simple_text(self, encoder):
        """Test tokenizing simple text."""
        tokens = encoder.tokenize("Solar flares emit radiation")
        assert "solar" in tokens
        assert "flares" in tokens
        assert "emit" in tokens
        assert "radiation" in tokens

    def test_tokenize_removes_stopwords(self, encoder):
        """Test that stopwords are removed."""
        tokens = encoder.tokenize("The solar flare is a phenomenon")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "a" not in tokens
        assert "solar" in tokens
        assert "flare" in tokens

    def test_tokenize_removes_short_tokens(self, encoder):
        """Test that tokens with 2 or fewer characters are removed."""
        tokens = encoder.tokenize("A B C solar X Y Z")
        assert len([t for t in tokens if len(t) <= 2]) == 0
        assert "solar" in tokens

    def test_tokenize_lowercases(self, encoder):
        """Test that text is lowercased."""
        tokens = encoder.tokenize("SOLAR Flare CORONA")
        assert "solar" in tokens
        assert "flare" in tokens
        assert "corona" in tokens
        assert "SOLAR" not in tokens

    def test_tokenize_handles_hyphenated_terms(self, encoder):
        """Test that hyphenated terms are preserved."""
        tokens = encoder.tokenize("X-ray emission from solar-wind")
        assert "x-ray" in tokens
        assert "solar-wind" in tokens

    def test_tokenize_handles_numbers(self, encoder):
        """Test that alphanumeric tokens are preserved."""
        tokens = encoder.tokenize("The temperature was 10000K in region AR12673")
        assert "10000k" in tokens
        assert "ar12673" in tokens

    def test_tokenize_empty_string(self, encoder):
        """Test tokenizing empty string."""
        tokens = encoder.tokenize("")
        assert tokens == []

    def test_tokenize_only_stopwords(self, encoder):
        """Test tokenizing text with only stopwords."""
        tokens = encoder.tokenize("the and or but if then")
        assert tokens == []

    def test_tokenize_scientific_stopwords(self, encoder):
        """Test that scientific stopwords are removed."""
        tokens = encoder.tokenize("See Fig 1 and Table 2 in Section 3")
        assert "fig" not in tokens
        assert "table" not in tokens
        assert "section" not in tokens


class TestSparseEncoderEncode:
    """Tests for SparseEncoder.encode."""

    @pytest.fixture
    def encoder(self):
        """Create a SparseEncoder for testing."""
        return SparseEncoder()

    def test_encode_creates_sparse_vector(self, encoder):
        """Test that encode returns indices and values."""
        result = encoder.encode("Solar flares emit X-ray radiation")
        assert "indices" in result
        assert "values" in result
        assert len(result["indices"]) == len(result["values"])
        assert len(result["indices"]) > 0

    def test_encode_builds_vocab(self, encoder):
        """Test that encoding builds vocabulary."""
        encoder.encode("solar flare corona")
        assert "solar" in encoder.vocab
        assert "flare" in encoder.vocab
        assert "corona" in encoder.vocab

    def test_encode_assigns_unique_indices(self, encoder):
        """Test that each term gets a unique index."""
        encoder.encode("solar flare corona hole")
        indices = list(encoder.vocab.values())
        assert len(indices) == len(set(indices))

    def test_encode_empty_text(self, encoder):
        """Test encoding empty text."""
        result = encoder.encode("")
        assert result == {"indices": [], "values": []}

    def test_encode_only_stopwords(self, encoder):
        """Test encoding text with only stopwords."""
        result = encoder.encode("the and or but")
        assert result == {"indices": [], "values": []}

    def test_encode_term_frequency_affects_weight(self, encoder):
        """Test that repeated terms have higher weights."""
        # Encode with repeated term
        result1 = encoder.encode("solar solar solar flare")
        solar_idx = encoder.vocab["solar"]
        flare_idx = encoder.vocab["flare"]

        solar_weight = result1["values"][result1["indices"].index(solar_idx)]
        flare_weight = result1["values"][result1["indices"].index(flare_idx)]

        # Solar appears 3x, flare 1x, so solar should have higher weight
        assert solar_weight > flare_weight

    def test_encode_uses_idf_scores(self):
        """Test that pre-computed IDF scores affect weights."""
        idf_scores = {"solar": 0.5, "flare": 2.0}  # flare is rarer
        vocab = {"solar": 0, "flare": 1}
        encoder = SparseEncoder(vocab=vocab, idf_scores=idf_scores)

        result = encoder.encode("solar flare")
        solar_idx = encoder.vocab["solar"]
        flare_idx = encoder.vocab["flare"]

        solar_weight = result["values"][result["indices"].index(solar_idx)]
        flare_weight = result["values"][result["indices"].index(flare_idx)]

        # Flare has higher IDF, should have higher weight (with same TF)
        assert flare_weight > solar_weight

    def test_encode_values_are_floats(self, encoder):
        """Test that all values are floats."""
        result = encoder.encode("solar flare corona emission")
        for value in result["values"]:
            assert isinstance(value, float)

    def test_encode_indices_are_integers(self, encoder):
        """Test that all indices are integers."""
        result = encoder.encode("solar flare corona emission")
        for idx in result["indices"]:
            assert isinstance(idx, int)


class TestSparseEncoderEncodeQuery:
    """Tests for SparseEncoder.encode_query."""

    @pytest.fixture
    def encoder(self):
        """Create a SparseEncoder with vocabulary."""
        vocab = {"solar": 0, "flare": 1, "corona": 2, "magnetic": 3}
        idf_scores = {"solar": 1.0, "flare": 1.5, "corona": 2.0, "magnetic": 1.2}
        return SparseEncoder(vocab=vocab, idf_scores=idf_scores)

    def test_encode_query_returns_sparse_vector(self, encoder):
        """Test that encode_query returns indices and values."""
        result = encoder.encode_query("solar flare")
        assert "indices" in result
        assert "values" in result
        assert len(result["indices"]) == len(result["values"])

    def test_encode_query_only_uses_known_terms(self, encoder):
        """Test that unknown terms are ignored in queries."""
        result = encoder.encode_query("solar unknown_term flare")
        # Should only have indices for solar and flare
        assert len(result["indices"]) == 2
        assert encoder.vocab["solar"] in result["indices"]
        assert encoder.vocab["flare"] in result["indices"]

    def test_encode_query_empty(self, encoder):
        """Test encoding empty query."""
        result = encoder.encode_query("")
        assert result == {"indices": [], "values": []}

    def test_encode_query_all_unknown_terms(self, encoder):
        """Test query with all unknown terms."""
        result = encoder.encode_query("unknown another_unknown")
        assert result == {"indices": [], "values": []}

    def test_encode_query_uses_idf_scores(self, encoder):
        """Test that query encoding uses IDF scores."""
        result = encoder.encode_query("solar corona")
        solar_idx = encoder.vocab["solar"]
        corona_idx = encoder.vocab["corona"]

        solar_weight = result["values"][result["indices"].index(solar_idx)]
        corona_weight = result["values"][result["indices"].index(corona_idx)]

        # Corona has higher IDF (2.0 vs 1.0)
        assert corona_weight > solar_weight


class TestSparseEncoderBuildIDF:
    """Tests for SparseEncoder.build_idf."""

    @pytest.fixture
    def encoder(self):
        """Create a SparseEncoder for testing."""
        return SparseEncoder()

    def test_build_idf_computes_scores(self, encoder):
        """Test that build_idf computes IDF scores."""
        documents = [
            "Solar flares emit radiation",
            "Corona is the outer atmosphere",
            "Solar wind flows from the corona",
        ]
        encoder.build_idf(documents)

        assert len(encoder.idf_scores) > 0
        assert "solar" in encoder.idf_scores
        assert "corona" in encoder.idf_scores

    def test_build_idf_rare_terms_higher_score(self, encoder):
        """Test that rare terms have higher IDF scores."""
        documents = [
            "solar flare corona",
            "solar wind corona",
            "solar emission",
            "magnetosphere uniqueterm",
        ]
        encoder.build_idf(documents)

        # "uniqueterm" appears in 1 doc, "solar" in 3
        assert encoder.idf_scores.get("uniqueterm", 0) > encoder.idf_scores.get("solar", 0)

    def test_build_idf_updates_avg_doc_length(self, encoder):
        """Test that build_idf computes average document length."""
        documents = [
            "word " * 100,  # ~100 tokens after stopword removal
            "term " * 50,   # ~50 tokens
        ]
        encoder.build_idf(documents)

        # Average should be around 75 (depends on stopword filtering)
        assert encoder.avg_doc_length > 0
        assert encoder.avg_doc_length != 200.0  # Should have changed from default

    def test_build_idf_empty_corpus(self, encoder):
        """Test build_idf with empty corpus."""
        encoder.build_idf([])
        assert encoder.idf_scores == {}
        assert encoder.avg_doc_length == 200.0  # Falls back to default

    def test_build_idf_single_document(self, encoder):
        """Test build_idf with single document."""
        encoder.build_idf(["solar flare corona magnetic field"])
        assert len(encoder.idf_scores) > 0

    def test_build_idf_builds_vocab(self, encoder):
        """Test that build_idf also builds vocabulary through tokenization."""
        documents = ["solar flare", "corona hole"]
        encoder.build_idf(documents)

        # Vocab is built through encode calls, but IDF uses tokenize
        # Terms should be in IDF scores
        assert "solar" in encoder.idf_scores
        assert "flare" in encoder.idf_scores
        assert "corona" in encoder.idf_scores
        assert "hole" in encoder.idf_scores


class TestSparseEncoderPersistence:
    """Tests for SparseEncoder.to_dict and from_dict."""

    def test_to_dict_exports_state(self):
        """Test that to_dict exports all state."""
        vocab = {"solar": 0, "flare": 1}
        idf_scores = {"solar": 1.5, "flare": 2.0}
        encoder = SparseEncoder(
            vocab=vocab,
            idf_scores=idf_scores,
            avg_doc_length=150.0,
        )

        data = encoder.to_dict()

        assert data["vocab"] == vocab
        assert data["idf_scores"] == idf_scores
        assert data["avg_doc_length"] == 150.0

    def test_from_dict_restores_state(self):
        """Test that from_dict restores encoder state."""
        data = {
            "vocab": {"corona": 0, "hole": 1},
            "idf_scores": {"corona": 1.2, "hole": 1.8},
            "avg_doc_length": 300.0,
        }

        encoder = SparseEncoder.from_dict(data)

        assert encoder.vocab == data["vocab"]
        assert encoder.idf_scores == data["idf_scores"]
        assert encoder.avg_doc_length == 300.0

    def test_from_dict_handles_missing_keys(self):
        """Test that from_dict handles missing keys with defaults."""
        data = {}
        encoder = SparseEncoder.from_dict(data)

        assert encoder.vocab == {}
        assert encoder.idf_scores == {}
        assert encoder.avg_doc_length == 200.0

    def test_roundtrip_preserves_state(self):
        """Test that to_dict -> from_dict preserves all state."""
        original = SparseEncoder(
            vocab={"term1": 0, "term2": 5, "term3": 10},
            idf_scores={"term1": 0.5, "term2": 1.5, "term3": 2.5},
            avg_doc_length=175.5,
        )

        data = original.to_dict()
        restored = SparseEncoder.from_dict(data)

        assert restored.vocab == original.vocab
        assert restored.idf_scores == original.idf_scores
        assert restored.avg_doc_length == original.avg_doc_length

    def test_roundtrip_produces_same_encodings(self):
        """Test that restored encoder produces same encodings."""
        original = SparseEncoder()
        original.build_idf([
            "solar flare emission",
            "corona magnetic field",
            "solar wind particles",
        ])

        # Encode some text
        original.encode("solar flare")
        original_result = original.encode("corona emission")

        # Roundtrip
        restored = SparseEncoder.from_dict(original.to_dict())
        restored_result = restored.encode("corona emission")

        assert original_result == restored_result


class TestGlobalEncoder:
    """Tests for global encoder functions."""

    def teardown_method(self):
        """Reset global encoder after each test."""
        import shared.utils.sparse_encoder as module
        module._global_encoder = None

    def test_get_sparse_encoder_creates_instance(self):
        """Test that get_sparse_encoder creates instance if none exists."""
        encoder = get_sparse_encoder()
        assert encoder is not None
        assert isinstance(encoder, SparseEncoder)

    def test_get_sparse_encoder_returns_same_instance(self):
        """Test that get_sparse_encoder returns same instance."""
        encoder1 = get_sparse_encoder()
        encoder2 = get_sparse_encoder()
        assert encoder1 is encoder2

    def test_set_sparse_encoder_replaces_instance(self):
        """Test that set_sparse_encoder sets global instance."""
        custom_encoder = SparseEncoder(avg_doc_length=999.0)
        set_sparse_encoder(custom_encoder)

        retrieved = get_sparse_encoder()
        assert retrieved is custom_encoder
        assert retrieved.avg_doc_length == 999.0

    def test_set_sparse_encoder_with_trained_encoder(self):
        """Test setting a trained encoder globally."""
        trained = SparseEncoder()
        trained.build_idf([
            "document one about solar physics",
            "document two about corona",
        ])
        trained.encode("solar corona")  # Build vocab

        set_sparse_encoder(trained)

        global_encoder = get_sparse_encoder()
        assert len(global_encoder.vocab) > 0
        assert len(global_encoder.idf_scores) > 0


class TestSparseEncoderIntegration:
    """Integration tests for realistic usage scenarios."""

    def test_index_and_search_workflow(self):
        """Test a complete index-and-search workflow."""
        # Create encoder and build IDF from corpus
        encoder = SparseEncoder()
        corpus = [
            "Solar flares are sudden eruptions of energy on the sun surface",
            "Coronal mass ejections release plasma into space",
            "The solar wind is a stream of charged particles from the sun",
            "Magnetic reconnection drives solar flares and CMEs",
            "Heliophysics studies the sun and its effects on the solar system",
        ]
        encoder.build_idf(corpus)

        # Index documents
        doc_vectors = []
        for doc in corpus:
            vec = encoder.encode(doc)
            doc_vectors.append(vec)
            assert len(vec["indices"]) > 0

        # Search query
        query_vec = encoder.encode_query("solar flares energy")

        # Query should have some overlap with corpus vocabulary
        assert len(query_vec["indices"]) > 0

        # Common terms should have indices in both
        if "solar" in encoder.vocab:
            solar_idx = encoder.vocab["solar"]
            # Solar appears in query and multiple docs
            docs_with_solar = sum(1 for v in doc_vectors if solar_idx in v["indices"])
            assert docs_with_solar >= 2

    def test_scientific_text_encoding(self):
        """Test encoding realistic scientific text."""
        encoder = SparseEncoder()

        abstract = """
        We present observations of a solar flare that occurred in active region
        AR12673 on September 6, 2017. The X9.3 flare was accompanied by a
        coronal mass ejection (CME) with speeds exceeding 1500 km/s. Analysis
        of SDO/AIA and RHESSI data reveals the thermal and non-thermal
        emission characteristics of this event.
        """

        result = encoder.encode(abstract)

        # Should extract meaningful scientific terms
        assert len(result["indices"]) > 5
        assert "observations" in encoder.vocab or "flare" in encoder.vocab
        assert "coronal" in encoder.vocab or "emission" in encoder.vocab

    def test_query_relevance(self):
        """Test that query encoding produces relevant matches."""
        encoder = SparseEncoder()

        # Build vocabulary and IDF
        docs = [
            "solar flare x-ray emission",
            "corona temperature measurement",
            "magnetic field reconnection",
        ]
        encoder.build_idf(docs)
        for doc in docs:
            encoder.encode(doc)

        # Query about flares
        query = encoder.encode_query("flare emission")

        # Should match terms from first document
        if "flare" in encoder.vocab and "emission" in encoder.vocab:
            assert encoder.vocab["flare"] in query["indices"] or \
                   encoder.vocab["emission"] in query["indices"]

    def test_bm25_length_normalization(self):
        """Test that document length affects term weights."""
        encoder = SparseEncoder(avg_doc_length=10.0)

        # Short document (below average)
        short_doc = "solar flare"
        short_result = encoder.encode(short_doc)

        # Reset and encode long document
        encoder2 = SparseEncoder(avg_doc_length=10.0)
        long_doc = "solar " + "additional term " * 20  # Much longer
        long_result = encoder2.encode(long_doc)

        # In BM25, same term in shorter doc gets higher weight
        # Both have "solar" with tf=1
        short_solar_weight = short_result["values"][0]
        long_solar_idx = encoder2.vocab["solar"]
        long_solar_weight = long_result["values"][long_result["indices"].index(long_solar_idx)]

        # Short doc should have higher weight for same term frequency
        assert short_solar_weight > long_solar_weight
