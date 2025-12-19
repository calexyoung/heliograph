-- Migration: Create extraction jobs table
-- Version: 003

-- Create extraction status enum
CREATE TYPE extraction_status AS ENUM (
    'pending',
    'in_progress',
    'completed',
    'failed'
);

-- Create extraction jobs table
CREATE TABLE extraction_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    status extraction_status NOT NULL DEFAULT 'pending',
    entity_count INTEGER DEFAULT 0,
    relationship_count INTEGER DEFAULT 0,
    error_message TEXT,
    worker_id VARCHAR(100),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes
CREATE INDEX idx_extraction_jobs_document ON extraction_jobs(document_id);
CREATE INDEX idx_extraction_jobs_status ON extraction_jobs(status);
CREATE INDEX idx_extraction_jobs_created ON extraction_jobs(created_at);
