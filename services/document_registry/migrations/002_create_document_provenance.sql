-- Migration: 002_create_document_provenance
-- Description: Create the document_provenance table for tracking document sources
-- Created: 2024-01-01

-- Up Migration
CREATE TABLE document_provenance (
    provenance_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES registry_documents(document_id) ON DELETE CASCADE,
    source VARCHAR(50) NOT NULL,  -- 'upload', 'crossref', 'semantic_scholar', 'arxiv', 'scixplorer'
    source_query TEXT,
    source_identifier VARCHAR(255),
    connector_job_id UUID,
    upload_id UUID,
    user_id UUID NOT NULL,
    metadata_snapshot JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_document_provenance_document_id ON document_provenance(document_id);
CREATE INDEX idx_document_provenance_user_id ON document_provenance(user_id);
CREATE INDEX idx_document_provenance_source ON document_provenance(source);
CREATE INDEX idx_document_provenance_created_at ON document_provenance(created_at);

-- Down Migration (comment out for rollback)
-- DROP TABLE IF EXISTS document_provenance;
