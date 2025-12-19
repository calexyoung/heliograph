-- Migration: 001_create_registry_documents
-- Description: Create the registry_documents table for storing document metadata
-- Created: 2024-01-01

-- Up Migration
CREATE TYPE document_status AS ENUM ('registered', 'processing', 'indexed', 'failed');

CREATE TABLE registry_documents (
    document_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doi VARCHAR(255) UNIQUE,
    content_hash VARCHAR(64) NOT NULL,
    title TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
    subtitle TEXT,
    journal VARCHAR(500),
    year INTEGER,
    authors JSONB NOT NULL DEFAULT '[]',
    source_metadata JSONB NOT NULL DEFAULT '{}',
    status document_status NOT NULL DEFAULT 'registered',
    error_message TEXT,
    artifact_pointers JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_processed_at TIMESTAMPTZ,
    UNIQUE (content_hash, title_normalized, year)
);

-- Indexes for common query patterns
CREATE INDEX idx_registry_documents_status ON registry_documents(status);
CREATE INDEX idx_registry_documents_doi ON registry_documents(doi) WHERE doi IS NOT NULL;
CREATE INDEX idx_registry_documents_content_hash ON registry_documents(content_hash);
CREATE INDEX idx_registry_documents_created_at ON registry_documents(created_at);
CREATE INDEX idx_registry_documents_year ON registry_documents(year) WHERE year IS NOT NULL;
CREATE INDEX idx_registry_documents_title_normalized ON registry_documents(title_normalized);

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_registry_documents_updated_at
    BEFORE UPDATE ON registry_documents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Down Migration (comment out for rollback)
-- DROP TRIGGER IF EXISTS update_registry_documents_updated_at ON registry_documents;
-- DROP FUNCTION IF EXISTS update_updated_at_column();
-- DROP TABLE IF EXISTS registry_documents;
-- DROP TYPE IF EXISTS document_status;
