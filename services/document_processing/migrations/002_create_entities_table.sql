-- Extracted entities table
-- Stores entities extracted from documents for knowledge graph construction

CREATE TABLE IF NOT EXISTS extracted_entities (
    entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    chunk_id UUID REFERENCES document_chunks(chunk_id) ON DELETE SET NULL,
    entity_type VARCHAR(50) NOT NULL,  -- concept, method, dataset, instrument, author, institution
    name VARCHAR(500) NOT NULL,
    normalized_name VARCHAR(500) NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 1.0,
    char_offset_start INTEGER,
    char_offset_end INTEGER,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_document FOREIGN KEY (document_id)
        REFERENCES registry_documents(document_id) ON DELETE CASCADE
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_entities_document ON extracted_entities(document_id);
CREATE INDEX IF NOT EXISTS idx_entities_chunk ON extracted_entities(chunk_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON extracted_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_normalized_name ON extracted_entities(normalized_name);
CREATE INDEX IF NOT EXISTS idx_entities_type_name ON extracted_entities(entity_type, normalized_name);

-- Comments
COMMENT ON TABLE extracted_entities IS 'Stores entities extracted from documents';
COMMENT ON COLUMN extracted_entities.entity_type IS 'Type: concept, method, dataset, instrument, author, institution';
COMMENT ON COLUMN extracted_entities.normalized_name IS 'Normalized/canonical form for deduplication';
COMMENT ON COLUMN extracted_entities.confidence IS 'Extraction confidence score (0-1)';
