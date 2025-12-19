-- Migration: Add storage_config column to uploads table
-- This column stores the storage configuration used for each upload,
-- enabling per-user storage preferences (S3 vs local filesystem).

-- Add storage_config column with default empty JSON object
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS storage_config JSONB NOT NULL DEFAULT '{}';

-- Add comment for documentation
COMMENT ON COLUMN uploads.storage_config IS 'Storage configuration: type (s3/local), local_path, bucket';
