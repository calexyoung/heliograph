-- Migration: 003_create_state_audit_log
-- Description: Create the document_state_audit table for tracking state transitions
-- Created: 2024-01-01

-- Up Migration
CREATE TABLE document_state_audit (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES registry_documents(document_id) ON DELETE CASCADE,
    previous_state document_status,
    new_state document_status NOT NULL,
    worker_id VARCHAR(100),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_state_audit_document_id ON document_state_audit(document_id);
CREATE INDEX idx_state_audit_created_at ON document_state_audit(created_at);
CREATE INDEX idx_state_audit_new_state ON document_state_audit(new_state);

-- Down Migration (comment out for rollback)
-- DROP TABLE IF EXISTS document_state_audit;
