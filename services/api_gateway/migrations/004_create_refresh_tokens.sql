-- Migration: 004_create_refresh_tokens
-- Description: Create refresh tokens table for JWT token rotation
-- Created: 2024-01-01

-- Up Migration
CREATE TABLE refresh_tokens (
    token_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    -- Token details
    token_hash VARCHAR(255) NOT NULL,  -- SHA-256 hash of the token

    -- Device/session info
    device_info JSONB DEFAULT '{}',
    ip_address INET,
    user_agent TEXT,

    -- Status
    is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at TIMESTAMPTZ,
    revoked_reason VARCHAR(100),

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ
);

-- Indexes
CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_token_hash ON refresh_tokens(token_hash);
CREATE INDEX idx_refresh_tokens_expires_at ON refresh_tokens(expires_at);
CREATE INDEX idx_refresh_tokens_active ON refresh_tokens(user_id, is_revoked) WHERE is_revoked = FALSE;

-- Down Migration
-- DROP TABLE IF EXISTS refresh_tokens;
