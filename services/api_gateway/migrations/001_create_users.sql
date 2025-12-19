-- Migration: 001_create_users
-- Description: Create users table for authentication
-- Created: 2024-01-01

-- Up Migration
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    hashed_password VARCHAR(255),  -- NULL for OAuth-only users
    full_name VARCHAR(255),
    avatar_url TEXT,

    -- OAuth provider info
    oauth_provider VARCHAR(50),  -- 'auth0', 'cognito', 'google', etc.
    oauth_subject VARCHAR(255),  -- Subject ID from OAuth provider

    -- Account status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_superuser BOOLEAN NOT NULL DEFAULT FALSE,

    -- Metadata
    preferences JSONB NOT NULL DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ,

    -- Unique constraint for OAuth users
    UNIQUE (oauth_provider, oauth_subject)
);

-- Indexes
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_oauth ON users(oauth_provider, oauth_subject) WHERE oauth_provider IS NOT NULL;
CREATE INDEX idx_users_created_at ON users(created_at);

-- Trigger for updated_at
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Down Migration
-- DROP TABLE IF EXISTS users;
