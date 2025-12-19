-- Migration: 002_create_api_keys
-- Description: Create API keys table for service-to-service authentication
-- Created: 2024-01-01

-- Up Migration
CREATE TABLE api_keys (
    key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,

    -- Key details
    name VARCHAR(100) NOT NULL,
    key_hash VARCHAR(255) NOT NULL,  -- SHA-256 hash of the API key
    key_prefix VARCHAR(8) NOT NULL,  -- First 8 chars for identification

    -- Permissions and scope
    scopes JSONB NOT NULL DEFAULT '[]',  -- List of allowed scopes
    rate_limit_override INTEGER,  -- Override default rate limit

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ
);

-- Indexes
CREATE INDEX idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX idx_api_keys_key_prefix ON api_keys(key_prefix);
CREATE INDEX idx_api_keys_active ON api_keys(is_active) WHERE is_active = TRUE;

-- Down Migration
-- DROP TABLE IF EXISTS api_keys;
