-- Migration: 004_add_deleted_at_and_content_hash_unique
-- Description: Add deleted_at column for soft delete support and unique constraint on content_hash

-- Add deleted_at column for soft deletes
ALTER TABLE registry_documents ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- Create index for efficient queries on active (non-deleted) documents
CREATE INDEX IF NOT EXISTS idx_registry_documents_active
ON registry_documents (created_at DESC)
WHERE deleted_at IS NULL;

-- Add unique constraint on content_hash for atomic INSERT ON CONFLICT
-- Note: This is separate from the composite unique (content_hash, title_normalized, year)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'registry_documents_content_hash_unique'
    ) THEN
        ALTER TABLE registry_documents
        ADD CONSTRAINT registry_documents_content_hash_unique UNIQUE (content_hash);
    END IF;
END
$$;
