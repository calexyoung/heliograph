-- Migration: 003_create_uploads
-- Description: Create uploads table for tracking file uploads
-- Created: 2024-01-01

-- Up Migration
CREATE TYPE upload_status AS ENUM ('pending', 'uploaded', 'processing', 'completed', 'failed');

CREATE TABLE uploads (
    upload_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    -- File details
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    size_bytes BIGINT NOT NULL,

    -- S3 location
    s3_key VARCHAR(500) NOT NULL,
    s3_bucket VARCHAR(100) NOT NULL,

    -- Status tracking
    status upload_status NOT NULL DEFAULT 'pending',
    error_message TEXT,

    -- Linked document (after processing)
    document_id UUID,  -- References registry_documents when processing complete

    -- Content hash (calculated after upload)
    content_hash VARCHAR(64),

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    uploaded_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- Indexes
CREATE INDEX idx_uploads_user_id ON uploads(user_id);
CREATE INDEX idx_uploads_status ON uploads(status);
CREATE INDEX idx_uploads_created_at ON uploads(created_at);

-- Down Migration
-- DROP TABLE IF EXISTS uploads;
-- DROP TYPE IF EXISTS upload_status;
