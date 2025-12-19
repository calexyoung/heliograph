-- Migration: 001_create_ingestion_jobs
-- Description: Create ingestion_jobs table for tracking upload and import jobs
-- Created: 2024-01-01

-- Up Migration
CREATE TYPE job_type AS ENUM ('upload', 'import', 'batch', 'search');
CREATE TYPE job_status AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled');

CREATE TABLE ingestion_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    job_type job_type NOT NULL,
    status job_status NOT NULL DEFAULT 'pending',

    -- Job details
    source VARCHAR(50),  -- 'crossref', 'semantic_scholar', 'arxiv', 'scixplorer', 'upload'
    query TEXT,  -- Search query or identifier

    -- Progress tracking
    progress JSONB NOT NULL DEFAULT '{}',
    total_items INTEGER DEFAULT 0,
    processed_items INTEGER DEFAULT 0,

    -- Results
    result_data JSONB DEFAULT '{}',
    error_message TEXT,

    -- Related entities
    document_ids UUID[] DEFAULT '{}',
    upload_ids UUID[] DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- Indexes
CREATE INDEX idx_ingestion_jobs_user_id ON ingestion_jobs(user_id);
CREATE INDEX idx_ingestion_jobs_status ON ingestion_jobs(status);
CREATE INDEX idx_ingestion_jobs_job_type ON ingestion_jobs(job_type);
CREATE INDEX idx_ingestion_jobs_created_at ON ingestion_jobs(created_at);

-- Trigger for updated_at
CREATE TRIGGER update_ingestion_jobs_updated_at
    BEFORE UPDATE ON ingestion_jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Down Migration
-- DROP TRIGGER IF EXISTS update_ingestion_jobs_updated_at ON ingestion_jobs;
-- DROP TABLE IF EXISTS ingestion_jobs;
-- DROP TYPE IF EXISTS job_status;
-- DROP TYPE IF EXISTS job_type;
