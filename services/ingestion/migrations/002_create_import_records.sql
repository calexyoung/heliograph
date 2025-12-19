-- Migration: 002_create_import_records
-- Description: Create import_records table for tracking external API imports
-- Created: 2024-01-01

-- Up Migration
CREATE TYPE import_status AS ENUM ('pending', 'downloading', 'processing', 'completed', 'failed');

CREATE TABLE import_records (
    import_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES ingestion_jobs(job_id) ON DELETE CASCADE,
    user_id UUID NOT NULL,

    -- Source information
    source VARCHAR(50) NOT NULL,  -- 'crossref', 'semantic_scholar', 'arxiv', 'scixplorer'
    external_id VARCHAR(255) NOT NULL,  -- DOI, arXiv ID, bibcode, etc.

    -- Fetched metadata
    title TEXT,
    authors JSONB DEFAULT '[]',
    year INTEGER,
    doi VARCHAR(255),
    abstract TEXT,
    source_metadata JSONB DEFAULT '{}',

    -- PDF handling
    pdf_url TEXT,
    s3_key VARCHAR(500),
    content_hash VARCHAR(64),

    -- Status
    status import_status NOT NULL DEFAULT 'pending',
    error_message TEXT,

    -- Result
    document_id UUID,  -- After successful registration

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Indexes
CREATE INDEX idx_import_records_job_id ON import_records(job_id);
CREATE INDEX idx_import_records_user_id ON import_records(user_id);
CREATE INDEX idx_import_records_source ON import_records(source);
CREATE INDEX idx_import_records_external_id ON import_records(external_id);
CREATE INDEX idx_import_records_status ON import_records(status);
CREATE UNIQUE INDEX idx_import_records_source_external_id ON import_records(source, external_id);

-- Down Migration
-- DROP TABLE IF EXISTS import_records;
-- DROP TYPE IF EXISTS import_status;
