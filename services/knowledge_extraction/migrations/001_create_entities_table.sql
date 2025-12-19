-- Migration: Create entities table for knowledge extraction
-- Version: 001

-- Create entity type enum
CREATE TYPE entity_type AS ENUM (
    'scientific_concept',
    'method',
    'dataset',
    'instrument',
    'phenomenon',
    'mission',
    'spacecraft',
    'celestial_body',
    'organization',
    'author'
);

-- Create entities table
CREATE TABLE entities (
    entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(500) NOT NULL,
    canonical_name VARCHAR(500) NOT NULL,
    entity_type entity_type NOT NULL,
    aliases TEXT[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes
CREATE INDEX idx_entities_canonical_name ON entities(canonical_name);
CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_canonical_name_type ON entities(canonical_name, entity_type);

-- Create entity mentions table
CREATE TABLE entity_mentions (
    mention_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    document_id UUID NOT NULL,
    chunk_id UUID NOT NULL,
    text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    confidence FLOAT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes for mentions
CREATE INDEX idx_entity_mentions_entity ON entity_mentions(entity_id);
CREATE INDEX idx_entity_mentions_document ON entity_mentions(document_id);
CREATE INDEX idx_entity_mentions_chunk ON entity_mentions(chunk_id);
