-- Document chunks table
-- Stores individual text chunks for vector search and retrieval

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    sequence_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    section VARCHAR(100),
    page_start INTEGER,
    page_end INTEGER,
    char_offset_start INTEGER NOT NULL,
    char_offset_end INTEGER NOT NULL,
    token_count INTEGER NOT NULL,
    embedding_id VARCHAR(255),  -- Qdrant point ID
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_document FOREIGN KEY (document_id)
        REFERENCES registry_documents(document_id) ON DELETE CASCADE
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document_section ON document_chunks(document_id, section);
CREATE INDEX IF NOT EXISTS idx_chunks_document_sequence ON document_chunks(document_id, sequence_number);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_id ON document_chunks(embedding_id) WHERE embedding_id IS NOT NULL;

-- Comments
COMMENT ON TABLE document_chunks IS 'Stores text chunks extracted from documents for RAG retrieval';
COMMENT ON COLUMN document_chunks.chunk_id IS 'Unique identifier for the chunk';
COMMENT ON COLUMN document_chunks.document_id IS 'Reference to the source document';
COMMENT ON COLUMN document_chunks.sequence_number IS 'Order of chunk within document';
COMMENT ON COLUMN document_chunks.section IS 'Document section this chunk belongs to';
COMMENT ON COLUMN document_chunks.embedding_id IS 'Qdrant point ID for the embedding';
