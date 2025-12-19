-- Migration: Create relationships table for knowledge extraction
-- Version: 002

-- Create relationship type enum
CREATE TYPE relationship_type AS ENUM (
    'cites',
    'authored_by',
    'uses_method',
    'uses_dataset',
    'uses_instrument',
    'studies',
    'mentions',
    'related_to',
    'part_of',
    'causes',
    'observes'
);

-- Create relationships table
CREATE TABLE relationships (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_entity_id UUID NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    relationship_type relationship_type NOT NULL,
    document_id UUID NOT NULL,
    confidence FLOAT NOT NULL,
    evidence JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes
CREATE INDEX idx_relationships_source ON relationships(source_entity_id);
CREATE INDEX idx_relationships_target ON relationships(target_entity_id);
CREATE INDEX idx_relationships_document ON relationships(document_id);
CREATE INDEX idx_relationships_type ON relationships(relationship_type);

-- Prevent duplicate relationships
CREATE UNIQUE INDEX idx_relationships_unique ON relationships(
    source_entity_id, target_entity_id, relationship_type, document_id
);
