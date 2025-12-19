# HelioGraph RAG - Implementation Plan

This document provides a detailed, phased implementation plan with checklists for building the HelioGraph RAG platform.

---

## Phase 0: Project Foundation & Infrastructure

### 0.1 Repository Setup

- [ ] Initialize monorepo structure
  ```
  heliograph/
  ├── services/
  │   ├── api-gateway/
  │   ├── document-registry/
  │   ├── ingestion/
  │   ├── document-processing/
  │   ├── knowledge-extraction/
  │   ├── query-orchestrator/
  │   └── llm-generation/
  ├── frontend/
  ├── shared/
  │   ├── schemas/        # Pydantic models shared across services
  │   └── utils/
  ├── infrastructure/
  │   ├── docker/
  │   ├── terraform/      # AWS deployment (optional)
  │   └── k8s/            # Kubernetes manifests (optional)
  ├── scripts/
  ├── tests/
  │   ├── unit/
  │   ├── integration/
  │   └── load/
  └── docs/
  ```
- [ ] Create `pyproject.toml` with shared dependencies
- [ ] Configure Python version (3.11+)
- [ ] Set up pre-commit hooks (black, ruff, mypy)
- [ ] Create `.env.example` with required environment variables
- [ ] Set up GitHub Actions CI pipeline
  - [ ] Lint job (ruff, black --check)
  - [ ] Type check job (mypy)
  - [ ] Unit test job (pytest)
  - [ ] Integration test job (pytest with test containers)

### 0.2 Local Development Environment

- [ ] Create `docker-compose.yml` for local services:
  - [ ] PostgreSQL 15+
  - [ ] Qdrant (vector DB)
  - [ ] Neo4j (graph DB)
  - [ ] Redis
  - [ ] LocalStack (S3 emulation) or MinIO
  - [ ] ElasticMQ (SQS emulation) or local queue
- [ ] Create `docker-compose.override.yml` for development settings
- [ ] Write `scripts/setup-local.sh` to initialize databases and seed data
- [ ] Document local setup in `docs/LOCAL_DEVELOPMENT.md`

### 0.3 Shared Infrastructure Code

- [ ] Create `shared/schemas/` Pydantic models:
  - [ ] `document.py` - Document metadata models
  - [ ] `author.py` - Author models
  - [ ] `events.py` - SQS event schemas (DocumentRegistered, etc.)
  - [ ] `api_responses.py` - Standard API response envelopes
- [ ] Create `shared/utils/`:
  - [ ] `logging.py` - Structured logging with correlation ID support
  - [ ] `metrics.py` - Prometheus metrics helpers
  - [ ] `s3.py` - S3 client wrapper with pre-signed URL generation
  - [ ] `sqs.py` - SQS publisher/consumer helpers
  - [ ] `db.py` - Database session management (SQLAlchemy async)

### 0.4 Observability Setup

- [ ] Set up Prometheus for metrics collection
- [ ] Set up Grafana for dashboards
- [ ] Create base dashboard templates:
  - [ ] Service health dashboard
  - [ ] Ingestion pipeline dashboard
  - [ ] Query latency dashboard
- [ ] Configure structured logging format (JSON)
- [ ] Set up log aggregation (Loki or ELK stack for local)

---

## Phase 1: Document Registry Service

**Owner:** Backend Team
**Target:** First service to reach production-ready state

### 1.1 Database Layer

- [ ] Create SQL migration: `001_create_registry_documents.sql`
  ```sql
  CREATE TYPE document_status AS ENUM ('registered', 'processing', 'indexed', 'failed');

  CREATE TABLE registry_documents (
    document_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doi VARCHAR(255) UNIQUE,
    content_hash VARCHAR(64) NOT NULL,
    title TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
    subtitle TEXT,
    journal VARCHAR(500),
    year INTEGER,
    authors JSONB NOT NULL DEFAULT '[]',
    source_metadata JSONB NOT NULL DEFAULT '{}',
    status document_status NOT NULL DEFAULT 'registered',
    error_message TEXT,
    artifact_pointers JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_processed_at TIMESTAMPTZ,
    UNIQUE (content_hash, title_normalized, year)
  );

  CREATE INDEX idx_registry_documents_status ON registry_documents(status);
  CREATE INDEX idx_registry_documents_doi ON registry_documents(doi) WHERE doi IS NOT NULL;
  CREATE INDEX idx_registry_documents_content_hash ON registry_documents(content_hash);
  CREATE INDEX idx_registry_documents_created_at ON registry_documents(created_at);
  ```
- [ ] Create SQL migration: `002_create_document_provenance.sql`
  ```sql
  CREATE TABLE document_provenance (
    provenance_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES registry_documents(document_id),
    source VARCHAR(50) NOT NULL,  -- 'upload', 'crossref', 'semantic_scholar', 'arxiv', 'scixplorer'
    source_query TEXT,
    source_identifier VARCHAR(255),
    connector_job_id UUID,
    upload_id UUID,
    user_id UUID NOT NULL,
    metadata_snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );

  CREATE INDEX idx_document_provenance_document_id ON document_provenance(document_id);
  ```
- [ ] Create SQL migration: `003_create_state_audit_log.sql`
  ```sql
  CREATE TABLE document_state_audit (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES registry_documents(document_id),
    previous_state document_status,
    new_state document_status NOT NULL,
    worker_id VARCHAR(100),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );

  CREATE INDEX idx_state_audit_document_id ON document_state_audit(document_id);
  ```
- [ ] Set up Alembic for migration management
- [ ] Create rollback scripts for each migration
- [ ] Test migrations on clean database
- [ ] Test rollback scripts

### 1.2 Service Scaffolding

- [ ] Create FastAPI application structure:
  ```
  services/document-registry/
  ├── app/
  │   ├── __init__.py
  │   ├── main.py           # FastAPI app entry
  │   ├── config.py         # Settings via pydantic-settings
  │   ├── dependencies.py   # Dependency injection
  │   ├── api/
  │   │   ├── __init__.py
  │   │   ├── routes.py     # API endpoints
  │   │   └── schemas.py    # Request/response models
  │   ├── core/
  │   │   ├── __init__.py
  │   │   ├── dedup.py      # Deduplication logic
  │   │   ├── state_machine.py  # State transitions
  │   │   └── normalizers.py    # Title/metadata normalization
  │   ├── db/
  │   │   ├── __init__.py
  │   │   ├── models.py     # SQLAlchemy models
  │   │   └── repository.py # Database operations
  │   └── events/
  │       ├── __init__.py
  │       └── publisher.py  # SQS event publisher
  ├── tests/
  ├── Dockerfile
  └── pyproject.toml
  ```
- [ ] Implement `config.py` with environment-based settings
- [ ] Implement database connection pool (asyncpg + SQLAlchemy async)
- [ ] Add health check endpoint: `GET /health`
- [ ] Add readiness check endpoint: `GET /ready`
- [ ] Implement service token authentication middleware
- [ ] Implement correlation ID middleware (extract from header or generate)
- [ ] Configure structured logging with correlation ID injection

### 1.3 API Endpoints

#### POST /registry/documents
- [ ] Define request schema:
  ```python
  class DocumentRegistrationRequest(BaseModel):
      doi: Optional[str] = None
      content_hash: str  # SHA-256 of PDF content
      title: str
      authors: List[AuthorSchema]
      journal: Optional[str] = None
      year: Optional[int] = None
      source: Literal['upload', 'crossref', 'semantic_scholar', 'arxiv']
      upload_id: Optional[UUID] = None
      connector_job_id: Optional[UUID] = None
      user_id: UUID
      source_metadata: Optional[dict] = None
  ```
- [ ] Define response schema:
  ```python
  class DocumentRegistrationResponse(BaseModel):
      document_id: UUID
      status: Literal['queued', 'duplicate', 'rejected']
      existing_document_id: Optional[UUID] = None  # If duplicate
      rejection_reason: Optional[str] = None
  ```
- [ ] Implement title normalization (lowercase, strip punctuation, collapse whitespace)
- [ ] Implement DOI normalization (lowercase, strip protocol prefixes)
- [ ] Implement dedup check logic:
  1. Check DOI match (exact)
  2. Check content_hash match (exact)
  3. Check (content_hash, title_normalized, year) match
  4. Fuzzy title match with Levenshtein ratio ≥ 0.9 on same year
- [ ] On duplicate: merge metadata, store provenance, return existing document_id
- [ ] On new: insert document, insert provenance, publish `DocumentRegistered` event
- [ ] Implement idempotency: same content_hash returns existing record without side effects
- [ ] Add request validation with clear error messages

#### GET /registry/documents/{document_id}
- [ ] Define response schema:
  ```python
  class DocumentDetailResponse(BaseModel):
      document_id: UUID
      doi: Optional[str]
      content_hash: str
      title: str
      authors: List[AuthorSchema]
      journal: Optional[str]
      year: Optional[int]
      status: DocumentStatus
      error_message: Optional[str]
      artifact_pointers: dict  # Links to S3 artifacts
      provenance: List[ProvenanceEntry]
      created_at: datetime
      updated_at: datetime
      last_processed_at: Optional[datetime]
  ```
- [ ] Implement endpoint with joined provenance data
- [ ] Return 404 for non-existent document_id

#### POST /registry/documents/{document_id}/state
- [ ] Define request schema:
  ```python
  class StateTransitionRequest(BaseModel):
      state: DocumentStatus
      expected_state: Optional[DocumentStatus] = None  # Optimistic locking
      worker_id: str
      error_message: Optional[str] = None  # Required if state == 'failed'
      artifact_pointers: Optional[dict] = None  # Updated artifacts
  ```
- [ ] Define valid state transitions:
  ```
  registered -> processing
  processing -> indexed
  processing -> failed
  failed -> processing  # Retry
  ```
- [ ] Implement optimistic locking: if expected_state provided and doesn't match, return 409 Conflict
- [ ] Write audit log entry for every transition
- [ ] Update `last_processed_at` on successful transition
- [ ] Return 400 for invalid transitions with clear error taxonomy

### 1.4 Deduplication Logic

- [ ] Implement `core/dedup.py`:
  ```python
  class DeduplicationService:
      async def check_duplicate(self, request: DocumentRegistrationRequest) -> Optional[DuplicateResult]:
          # 1. DOI exact match
          # 2. Content hash exact match
          # 3. (hash, normalized_title, year) composite match
          # 4. Fuzzy title match (Levenshtein >= 0.9) on same year
          pass

      async def merge_metadata(self, existing: Document, new_request: DocumentRegistrationRequest) -> Document:
          # Merge source_metadata, add provenance entry
          pass
  ```
- [ ] Install and configure `python-Levenshtein` or `rapidfuzz` for fuzzy matching
- [ ] Write unit tests for each dedup path:
  - [ ] DOI match
  - [ ] Content hash match
  - [ ] Composite key match
  - [ ] Fuzzy title match (edge cases: 0.89 vs 0.90 ratio)
  - [ ] No match (new document)
- [ ] Write concurrency tests simulating duplicate submissions

### 1.5 Event Publishing

- [ ] Implement `events/publisher.py`:
  ```python
  class DocumentEventPublisher:
      async def publish_document_registered(self, document: Document) -> None:
          event = DocumentRegisteredEvent(
              document_id=document.document_id,
              content_hash=document.content_hash,
              doi=document.doi,
              title=document.title,
              s3_key=...,  # Derive from upload_id or connector_job_id
              correlation_id=get_correlation_id(),
              timestamp=datetime.utcnow()
          )
          await self.sqs_client.send_message(queue_url, event.json())
  ```
- [ ] Define event schemas in `shared/schemas/events.py`:
  - [ ] `DocumentRegisteredEvent`
  - [ ] `DocumentDuplicateEvent`
  - [ ] `StateTransitionFailedEvent`
- [ ] Implement dead-letter queue handling for failed publishes
- [ ] Add metrics: `registry_events_published_total`, `registry_events_failed_total`

### 1.6 Observability

- [ ] Add Prometheus metrics:
  - [ ] `registry_requests_total` (labels: endpoint, status_code)
  - [ ] `registry_request_duration_seconds` (histogram)
  - [ ] `registry_dedup_hits_total` (labels: match_type)
  - [ ] `registry_conflicts_total`
  - [ ] `registry_state_transitions_total` (labels: from_state, to_state)
- [ ] Create Grafana dashboard for Document Registry
- [ ] Write on-call runbook entry:
  - [ ] How to identify duplicate conflicts
  - [ ] How to manually reconcile state drift
  - [ ] How to trigger reprocessing for failed documents

### 1.7 Testing

- [ ] Unit tests (pytest):
  - [ ] Title normalization
  - [ ] DOI normalization
  - [ ] Dedup logic (all paths)
  - [ ] State machine transitions (valid and invalid)
  - [ ] Request validation
- [ ] Integration tests (pytest + testcontainers):
  - [ ] Full registration flow with real Postgres
  - [ ] Concurrent duplicate submissions
  - [ ] State transition sequences
  - [ ] SQS event publishing (with LocalStack)
- [ ] Load tests (Locust):
  - [ ] 100 concurrent registrations
  - [ ] Mixed read/write workload
- [ ] Achieve ≥80% code coverage

### 1.8 Deployment

- [ ] Create Dockerfile with multi-stage build
- [ ] Create Kubernetes deployment manifest (or ECS task definition)
- [ ] Configure health check probes
- [ ] Set up feature flag for shadow-write mode
- [ ] Deploy to staging behind feature flag
- [ ] Run shadow-write validation:
  - [ ] Compare registry output with legacy dedup (if applicable)
  - [ ] Verify no duplicate documents created
- [ ] Cut over to registry as source-of-truth
- [ ] Remove legacy dedup code

---

## Phase 2: API Gateway / BFF

### 2.1 Authentication & Authorization

- [ ] Implement OAuth 2.0 / OIDC integration (Auth0, Cognito, or self-hosted)
- [ ] Create `User` model and database table
- [ ] Implement JWT validation middleware
- [ ] Implement API key authentication for service-to-service calls
- [ ] Create user session management with Redis
- [ ] Implement rate limiting:
  - [ ] Per-user limits (requests/minute)
  - [ ] Per-endpoint limits
  - [ ] Configurable via environment

### 2.2 Request Routing

- [ ] Set up API routes to backend services:
  - [ ] `/api/documents/*` → Document Registry
  - [ ] `/api/upload/*` → Ingestion Service
  - [ ] `/api/search/*` → Ingestion Service (connectors)
  - [ ] `/api/query/*` → Query Orchestrator
  - [ ] `/api/graph/*` → Knowledge Extraction Service
- [ ] Implement request/response logging with correlation IDs
- [ ] Add request validation at gateway level
- [ ] Implement circuit breaker for downstream services

### 2.3 File Upload Handling

- [ ] Implement pre-signed URL generation endpoint:
  ```
  POST /api/upload/presigned-url
  Request: { filename: string, content_type: string, size_bytes: number }
  Response: { upload_id: UUID, presigned_url: string, expires_at: datetime }
  ```
- [ ] Validate file size limits (configurable, default 50MB)
- [ ] Validate content type (application/pdf only for MVP)
- [ ] Implement upload completion callback:
  ```
  POST /api/upload/{upload_id}/complete
  ```
- [ ] Trigger document registration on upload completion

### 2.4 WebSocket / SSE Support

- [ ] Implement WebSocket endpoint for real-time updates:
  ```
  WS /api/ws/jobs/{job_id}
  ```
- [ ] Implement SSE endpoint as fallback:
  ```
  GET /api/events/jobs/{job_id}
  ```
- [ ] Create job status update publisher (Redis pub/sub)
- [ ] Implement client heartbeat and reconnection handling

### 2.5 API Documentation

- [ ] Configure OpenAPI/Swagger documentation
- [ ] Add detailed descriptions for all endpoints
- [ ] Include example requests/responses
- [ ] Document error codes and messages

---

## Phase 3: Ingestion Service

### 3.1 PDF Upload Path

- [ ] Implement upload completion handler:
  - [ ] Verify file exists in S3
  - [ ] Calculate content_hash (SHA-256)
  - [ ] Extract basic metadata (if possible from filename)
  - [ ] Call Document Registry to register
- [ ] Implement batch upload support (ZIP file containing PDFs)
- [ ] Add virus scanning integration (ClamAV or AWS-native)

### 3.2 External API Connectors

#### Crossref Connector
- [ ] Implement Crossref API client
- [ ] Search endpoint: query by title, author, DOI
- [ ] Metadata fetching: retrieve full bibliographic data
- [ ] PDF URL extraction (when available)
- [ ] Rate limiting compliance (polite pool)
- [ ] Error handling and retry logic

#### Semantic Scholar Connector
- [ ] Implement Semantic Scholar API client
- [ ] Search endpoint with filters
- [ ] Paper details fetching
- [ ] Citation graph retrieval (for future phases)
- [ ] API key management
- [ ] Rate limiting compliance

#### arXiv Connector
- [ ] Implement arXiv API client
- [ ] Search by title, author, category
- [ ] PDF download from arXiv
- [ ] Metadata parsing from Atom feed
- [ ] Rate limiting (3 second delay between requests)

#### SciXplorer Connector (NASA Science Explorer / ADS)
- [ ] Implement SciXplorer API client
  - [ ] Base URL: `https://api.adsabs.harvard.edu/v1/`
  - [ ] Bearer token authentication via `Authorization` header
- [ ] Search endpoint: `/search/query`
  - [ ] Query by title, author, DOI, bibcode
  - [ ] Filter by year, collection (astronomy, physics, heliophysics)
  - [ ] Field selection for optimized metadata retrieval
- [ ] Paper metadata fetching via bibcode identifier
- [ ] PDF/full-text URL extraction (when available via `esources` field)
- [ ] Rate limiting compliance:
  - [ ] Default: 5,000 requests/day
  - [ ] Track via `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers
  - [ ] Implement backoff when approaching limit
  - [ ] Handle 429 responses with exponential backoff
- [ ] Consider using `ads` Python library (ads.readthedocs.io) as client
- [ ] API token management and secure storage

### 3.3 Connector Orchestration

- [ ] Create unified search interface:
  ```
  POST /api/search
  Request: { query: string, sources: ['crossref', 'semantic_scholar', 'arxiv', 'scixplorer'], limit: int }
  Response: { results: SearchResult[], source_metadata: dict }
  ```
- [ ] Implement result deduplication across sources
- [ ] Implement import endpoint:
  ```
  POST /api/import
  Request: { source: string, identifier: string, user_id: UUID }
  ```
- [ ] Download PDF to S3
- [ ] Register with Document Registry
- [ ] Return job_id for status tracking

### 3.4 Job Management

- [ ] Create `ingestion_jobs` table:
  ```sql
  CREATE TABLE ingestion_jobs (
    job_id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    job_type VARCHAR(50) NOT NULL,  -- 'upload', 'import', 'batch'
    status VARCHAR(50) NOT NULL,
    progress JSONB DEFAULT '{}',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  ```
- [ ] Implement job status API:
  ```
  GET /api/jobs/{job_id}
  ```
- [ ] Publish job status updates to Redis for WebSocket delivery

---

## Phase 4: Document Processing Pipeline

### 4.1 Workflow Orchestrator

- [ ] Implement SQS consumer for `DocumentRegistered` events
- [ ] Create pipeline stage dispatcher
- [ ] Implement stage retry logic with exponential backoff
- [ ] Create dead-letter queue handler for permanently failed documents
- [ ] Implement reprocessing trigger endpoint:
  ```
  POST /api/documents/{document_id}/reprocess
  ```

### 4.2 PDF Parsing Stage

- [ ] Integrate GROBID for structured extraction:
  - [ ] Deploy GROBID as sidecar or separate service
  - [ ] Implement GROBID client
  - [ ] Extract: title, authors, abstract, sections, references
  - [ ] Handle GROBID failures gracefully
- [ ] Implement PDFMiner fallback for simple extraction
- [ ] Output artifacts:
  - [ ] `extracted_text.json` - Full text with structure
  - [ ] `structure_map.json` - Section boundaries
  - [ ] `references.json` - Parsed reference list
- [ ] Store artifacts in S3 under `documents/{document_id}/`
- [ ] Update Document Registry with artifact pointers

### 4.3 Section Segmentation

- [ ] Implement section classifier:
  - [ ] Abstract detection
  - [ ] Introduction
  - [ ] Methods/Materials
  - [ ] Results
  - [ ] Discussion
  - [ ] Conclusion
  - [ ] References
- [ ] Handle papers without clear sections
- [ ] Output section-annotated text

### 4.4 Chunking Stage

- [ ] Implement chunking service:
  ```python
  class ChunkingConfig:
      max_tokens: int = 512
      overlap_tokens: int = 50
      respect_section_boundaries: bool = True
  ```
- [ ] Create chunk records:
  ```python
  class Chunk:
      chunk_id: UUID
      document_id: UUID
      text: str
      section: Optional[str]
      page_start: int
      page_end: int
      char_offset_start: int
      char_offset_end: int
      token_count: int
  ```
- [ ] Store chunk metadata in Postgres
- [ ] Output `chunks.json` artifact

### 4.5 Embedding Generation Stage

- [ ] Integrate embedding model:
  - [ ] Option A: OpenAI `text-embedding-3-small` (cloud)
  - [ ] Option B: `sentence-transformers` local model (e.g., `all-MiniLM-L6-v2`)
  - [ ] Option C: `instructor-xl` for longer chunks
- [ ] Implement batched embedding generation
- [ ] Create Qdrant collection schema:
  ```python
  collection_config = {
      "vectors": {"size": 384, "distance": "Cosine"},  # Adjust for model
      "payload_schema": {
          "document_id": "uuid",
          "chunk_id": "uuid",
          "section": "keyword",
          "year": "integer",
          "authors": "keyword[]",
          "journal": "keyword"
      }
  }
  ```
- [ ] Implement upsert to Qdrant with metadata
- [ ] Handle embedding model failures with retry
- [ ] Add metrics: `embeddings_generated_total`, `embedding_latency_seconds`

### 4.6 Pipeline Completion

- [ ] Update Document Registry state to `indexed` on success
- [ ] Update Document Registry state to `failed` on permanent failure
- [ ] Publish `DocumentIndexed` event for downstream consumers
- [ ] Calculate and store processing metrics:
  - [ ] Total processing time
  - [ ] Stage-level timings
  - [ ] Chunk count
  - [ ] Embedding count

---

## Phase 5: Knowledge Extraction Service

### 5.1 Entity Extraction

- [ ] Implement entity extraction pipeline:
  - [ ] Scientific concepts (using domain-specific NER or LLM)
  - [ ] Methods and techniques
  - [ ] Datasets
  - [ ] Instruments
  - [ ] Authors (from metadata)
  - [ ] Institutions (from metadata)
- [ ] Create entity normalization:
  - [ ] Canonical forms for common entities
  - [ ] Alias resolution
- [ ] Store extracted entities with confidence scores

### 5.2 Relationship Extraction

- [ ] Implement relationship extraction:
  - [ ] `cites` - From reference parsing
  - [ ] `authored_by` - From metadata
  - [ ] `uses` - Method/dataset usage in text
  - [ ] `mentions` - Entity mentions
  - [ ] `related_to` - Semantic similarity
- [ ] Assign confidence scores to relationships
- [ ] Store evidence pointers (chunk_id + character offsets)

### 5.3 Neo4j Graph Construction

- [ ] Design graph schema:
  ```cypher
  // Node types
  (:Article {document_id, doi, title, year, ...})
  (:Author {name, normalized_name, affiliations})
  (:Entity {name, type, canonical_form})

  // Relationship types
  (a:Article)-[:CITES {confidence}]->(b:Article)
  (a:Article)-[:AUTHORED_BY]->(auth:Author)
  (a:Article)-[:MENTIONS {chunk_id, confidence, offsets}]->(e:Entity)
  (e1:Entity)-[:RELATED_TO {confidence, evidence}]->(e2:Entity)
  ```
- [ ] Implement incremental graph updates (not full rebuild)
- [ ] Add evidence metadata to all edges
- [ ] Implement graph versioning for schema migrations

### 5.4 Graph API

- [ ] Implement subgraph retrieval:
  ```
  GET /api/graph/subgraph
  Params: center_node_id, depth, node_types[], edge_types[], min_confidence
  Response: { nodes: Node[], edges: Edge[], evidence_refs: dict }
  ```
- [ ] Implement node search:
  ```
  GET /api/graph/search
  Params: query, node_type, limit
  ```
- [ ] Implement edge evidence lookup:
  ```
  GET /api/graph/edges/{edge_id}/evidence
  Response: { chunks: ChunkWithSnippet[], confidence, source_document }
  ```

---

## Phase 6: Query Orchestrator (RAG)

### 6.1 Query Understanding

- [ ] Implement query parser:
  - [ ] Intent classification (summary, compare, find evidence, explore)
  - [ ] Entity extraction from query
  - [ ] Constraint extraction (year range, authors, topics)
  - [ ] Query rewriting for retrieval

### 6.2 Vector Retrieval

- [ ] Implement Qdrant search:
  ```python
  async def search_vectors(
      query_embedding: List[float],
      filters: Optional[dict],
      top_k: int = 20
  ) -> List[SearchResult]
  ```
- [ ] Support metadata filtering:
  - [ ] Year range
  - [ ] Authors
  - [ ] Journals
  - [ ] Document IDs (for scoped search)
- [ ] Implement hybrid retrieval with BM25 (Phase 1+)

### 6.3 Graph-Augmented Retrieval

- [ ] Implement graph expansion:
  - [ ] From entities in top-K chunks, expand to neighboring nodes
  - [ ] Retrieve chunks associated with expanded entities
  - [ ] Apply graph-based filters from query constraints
- [ ] Implement graph-constrained retrieval:
  ```python
  # "papers that cite X and use method Y"
  graph_filter = GraphConstraint(
      must_cite=["document_id_1"],
      must_mention_entity=["method_Y"]
  )
  ```

### 6.4 Context Assembly

- [ ] Implement re-ranking:
  - [ ] Cross-encoder re-ranking for top candidates
  - [ ] MMR (Maximal Marginal Relevance) for diversity
- [ ] Implement context window management:
  - [ ] Select chunks that fit within LLM context limit
  - [ ] Prioritize by relevance score
  - [ ] Include metadata for citation generation

### 6.5 Evidence Tracking

- [ ] Create evidence map structure:
  ```python
  class EvidenceMap:
      chunks: List[ChunkEvidence]  # chunk_id, doc_id, page, section, snippet
      graph_paths: List[GraphPath]  # For graph-derived evidence
  ```
- [ ] Pass evidence map to generation service
- [ ] Return evidence in API response

---

## Phase 7: LLM Generation Service

### 7.1 Prompt Engineering

- [ ] Create system prompt template:
  - [ ] Role definition
  - [ ] Citation requirements
  - [ ] Abstention policy (must cite or say "I don't know")
  - [ ] Output format specification
- [ ] Create user prompt template with context injection
- [ ] Implement prompt injection defenses:
  - [ ] Strip instruction-like patterns from retrieved text
  - [ ] Use delimiters to separate context from query

### 7.2 LLM Integration

- [ ] Implement LLM client abstraction:
  ```python
  class LLMClient(Protocol):
      async def generate(self, messages: List[Message], **kwargs) -> GenerationResult
      async def stream(self, messages: List[Message], **kwargs) -> AsyncIterator[str]
  ```
- [ ] Implement OpenAI client
- [ ] Implement local model client (vLLM, Ollama)
- [ ] Implement Anthropic client (Claude)
- [ ] Add model configuration via environment

### 7.3 Response Generation

- [ ] Implement generation endpoint:
  ```
  POST /api/query
  Request: { query: string, corpus_ids?: UUID[], streaming: bool }
  Response: {
    answer: string,
    citations: Citation[],
    evidence: Evidence[],
    confidence: float
  }
  ```
- [ ] Implement streaming response with SSE
- [ ] Parse citations from LLM output
- [ ] Map citations to evidence chunks
- [ ] Include "sources so far" updates during streaming

### 7.4 Citation-Only Mode

- [ ] Implement strict citation mode:
  - [ ] Every claim must have inline citation
  - [ ] Abstain if insufficient evidence
  - [ ] Return confidence score based on evidence coverage
- [ ] Add configuration toggle for citation mode

---

## Phase 8: Frontend

### 8.1 Project Setup

- [ ] Initialize React project (Vite or Next.js)
- [ ] Set up TypeScript
- [ ] Configure Tailwind CSS or chosen styling
- [ ] Set up React Query for data fetching
- [ ] Configure routing (React Router or Next.js pages)
- [ ] Set up authentication flow

### 8.2 Document Upload View

- [ ] Drag-and-drop upload zone
- [ ] Upload progress indicator
- [ ] Batch upload support
- [ ] Upload completion notifications
- [ ] Error handling and retry UI

### 8.3 API Search & Import View

- [ ] Search form with source selection
- [ ] Search results list with metadata preview
- [ ] Import button with confirmation
- [ ] Import progress tracking
- [ ] Duplicate detection warnings

### 8.4 Corpus Overview View

- [ ] Document list with filtering:
  - [ ] By status (processing, indexed, failed)
  - [ ] By date range
  - [ ] By author/journal
  - [ ] Full-text search
- [ ] Document detail view:
  - [ ] Metadata display
  - [ ] Processing status
  - [ ] Extracted entities
  - [ ] PDF viewer with page navigation
- [ ] Bulk actions (reprocess, delete)

### 8.5 RAG Chat Interface

- [ ] Chat message list
- [ ] Query input with submit
- [ ] Streaming response display
- [ ] Inline citation markers (clickable)
- [ ] Citation panel (right sidebar):
  - [ ] Snippet text
  - [ ] Chunk metadata (doc, page, section)
  - [ ] "Open PDF to page" action
- [ ] "Sources so far" rail during streaming
- [ ] Conversation history

### 8.6 Knowledge Graph Visualization

- [ ] Graph rendering (D3.js, Cytoscape.js, or vis.js)
- [ ] Node/edge filtering:
  - [ ] By node type
  - [ ] By edge type
  - [ ] By confidence threshold
  - [ ] By year range
- [ ] Node click: show detail panel, link to document
- [ ] Edge click: show evidence panel with supporting chunks
- [ ] Zoom/pan controls
- [ ] Layout options (force-directed, hierarchical)
- [ ] Export graph view as image

### 8.7 Provenance Deep Links

- [ ] Document detail page with chunk ID parameter
- [ ] Highlight specific chunk on page load
- [ ] Scroll to chunk position
- [ ] Breadcrumb navigation back to source (chat or graph)

---

## Phase 9: Testing & Validation

### 9.1 Unit Tests

- [ ] Achieve ≥80% coverage on all services
- [ ] Test edge cases:
  - [ ] Empty inputs
  - [ ] Malformed PDFs
  - [ ] Unicode handling
  - [ ] Large documents

### 9.2 Integration Tests

- [ ] End-to-end ingestion flow
- [ ] End-to-end query flow
- [ ] WebSocket connection lifecycle
- [ ] Authentication flows
- [ ] Error propagation across services

### 9.3 Load Testing

- [ ] Ingestion load test:
  - [ ] 50 document batch
  - [ ] Target: ≤10 min avg, ≤20 min P95
- [ ] Query load test:
  - [ ] 30 concurrent chat sessions
  - [ ] Target: ≤8s P95 response time
- [ ] Graph rendering load test:
  - [ ] 200-node subgraph
  - [ ] Target: ≤3s to interactive

### 9.4 User Acceptance Testing

- [ ] Invite 3 beta researchers
- [ ] Provide test corpus
- [ ] Collect feedback on:
  - [ ] Ingestion experience
  - [ ] Query quality
  - [ ] Citation accuracy
  - [ ] Graph usability
- [ ] Document findings and prioritize fixes

---

## Phase 10: Deployment & Operations

### 10.1 Infrastructure Provisioning

- [ ] Provision AWS resources (or local equivalent):
  - [ ] ECS/EKS cluster for services
  - [ ] RDS PostgreSQL
  - [ ] ElastiCache Redis
  - [ ] S3 buckets
  - [ ] SQS queues
  - [ ] ALB/NLB
- [ ] Configure networking (VPC, security groups)
- [ ] Set up secrets management (AWS Secrets Manager or Vault)
- [ ] Configure auto-scaling policies

### 10.2 CI/CD Pipeline

- [ ] Build and push Docker images
- [ ] Run tests on PR
- [ ] Deploy to staging on merge to main
- [ ] Manual promotion to production
- [ ] Database migration automation
- [ ] Rollback procedures

### 10.3 Monitoring & Alerting

- [ ] Configure Prometheus alerting rules:
  - [ ] Service down
  - [ ] High error rate (>1%)
  - [ ] High latency (>SLA threshold)
  - [ ] Queue depth growing
  - [ ] Disk usage >80%
- [ ] Set up PagerDuty or equivalent
- [ ] Create on-call runbooks for each alert

### 10.4 Backup & Recovery

- [ ] Configure automated database backups
- [ ] Configure S3 lifecycle policies
- [ ] Document recovery procedures
- [ ] Test recovery from backup
- [ ] Configure Neo4j snapshots

### 10.5 Security Hardening

- [ ] Enable TLS everywhere
- [ ] Configure WAF rules
- [ ] Implement input sanitization
- [ ] Set up security scanning in CI (Snyk, Trivy)
- [ ] Document security incident response

---

## Appendix A: Performance Benchmarks

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| Ingest avg time | ≤10 min | Measure from upload complete to indexed |
| Ingest P95 time | ≤20 min | 20-page PDF, 50-document batch |
| RAG P95 latency | ≤8s | 1k document corpus, 30 concurrent users |
| Graph render time | ≤3s | 200-node subgraph, time to interactive |
| Vector search latency | ≤200ms | 500k chunks, top-20 retrieval |
| Dedup check latency | ≤50ms | Per-document registration |

---

## Appendix B: Hardware Requirements

### AWS Deployment (MVP)

| Component | Instance | Specs | Count |
|-----------|----------|-------|-------|
| API Gateway | c7g.large | 2 vCPU, 4 GiB | 2 |
| Workers | g5.xlarge | 4 vCPU, 16 GiB, A10G | 4 |
| Qdrant | m6i.xlarge | 4 vCPU, 16 GiB | 1 |
| Neo4j | r6i.xlarge | 4 vCPU, 32 GiB | 1 |
| PostgreSQL | db.r6g.large | 2 vCPU, 16 GiB | 1 |
| Redis | cache.r6g.large | 2 vCPU, 13 GiB | 1 |

### Local Deployment

| Component | Requirement |
|-----------|-------------|
| CPU | 12-core |
| RAM | 64 GiB |
| GPU | RTX 4090 or equivalent |
| Storage | 500 GiB NVMe |

---

## Appendix C: Event Schemas

```python
# DocumentRegistered - triggers processing pipeline
class DocumentRegisteredEvent(BaseModel):
    event_type: Literal["DocumentRegistered"] = "DocumentRegistered"
    document_id: UUID
    content_hash: str
    doi: Optional[str]
    title: str
    s3_key: str
    user_id: UUID
    correlation_id: str
    timestamp: datetime

# DocumentIndexed - signals completion
class DocumentIndexedEvent(BaseModel):
    event_type: Literal["DocumentIndexed"] = "DocumentIndexed"
    document_id: UUID
    chunk_count: int
    entity_count: int
    processing_time_seconds: float
    correlation_id: str
    timestamp: datetime

# StateTransitionFailed - for alerting
class StateTransitionFailedEvent(BaseModel):
    event_type: Literal["StateTransitionFailed"] = "StateTransitionFailed"
    document_id: UUID
    from_state: str
    to_state: str
    error_message: str
    worker_id: str
    correlation_id: str
    timestamp: datetime
```

---

## Appendix D: API Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `DUPLICATE_DOCUMENT` | 200 | Document already exists (returns existing ID) |
| `INVALID_DOI` | 400 | DOI format invalid |
| `INVALID_CONTENT_HASH` | 400 | Content hash format invalid |
| `DOCUMENT_NOT_FOUND` | 404 | Document ID does not exist |
| `INVALID_STATE_TRANSITION` | 400 | State transition not allowed |
| `STATE_CONFLICT` | 409 | Expected state doesn't match (optimistic lock) |
| `FILE_TOO_LARGE` | 413 | PDF exceeds size limit |
| `UNSUPPORTED_FORMAT` | 415 | File is not a PDF |
| `RATE_LIMITED` | 429 | Too many requests |
| `PROCESSING_FAILED` | 500 | Internal processing error |
