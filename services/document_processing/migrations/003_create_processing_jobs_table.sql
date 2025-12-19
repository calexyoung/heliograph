-- Processing jobs table
-- Tracks document processing pipeline execution

CREATE TABLE IF NOT EXISTS processing_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    current_stage VARCHAR(50),
    stages_completed JSONB DEFAULT '[]',
    stage_timings JSONB DEFAULT '{}',
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    worker_id VARCHAR(100),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    CONSTRAINT fk_document FOREIGN KEY (document_id)
        REFERENCES registry_documents(document_id) ON DELETE CASCADE,
    CONSTRAINT chk_status CHECK (status IN ('pending', 'running', 'completed', 'failed', 'retrying'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_processing_jobs_document ON processing_jobs(document_id);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON processing_jobs(status);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_created ON processing_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_pending ON processing_jobs(created_at)
    WHERE status = 'pending';

-- Comments
COMMENT ON TABLE processing_jobs IS 'Tracks document processing pipeline execution';
COMMENT ON COLUMN processing_jobs.current_stage IS 'Current processing stage: pdf_parsing, section_segmentation, chunking, embedding, indexing';
COMMENT ON COLUMN processing_jobs.stages_completed IS 'Array of completed stage names';
COMMENT ON COLUMN processing_jobs.stage_timings IS 'Timing in seconds for each stage';
