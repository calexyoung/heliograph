
This architecture describes a web platform that ingests PDF journal articles (via upload or external APIs), transforms them into a **vector-indexed document store** and a **property knowledge graph**, and exposes both through a **graph-aware RAG query service** with full provenance.

---
## 1) User Interaction Layer

**Web Client (Browser UI)** is the single entry point for:
- Uploading PDFs (single/batch)
- Searching and importing articles through external providers
- Exploring the knowledge graph visually
- Asking natural-language questions via a chat/query interface
- Inspecting citations and source passages

The UI communicates only with the **Backend API Gateway** over HTTPS, and subscribes to job updates (processing progress, completion) using **WebSockets or Server-Sent Events (SSE)**.

---
## 2) API Gateway and Auth Boundary

All requests first hit the **API Gateway / Backend-for-Frontend (BFF)**. This service:

- Authenticates users (OAuth or email-based login)
- Enforces authorization rules (per-user corpora in MVP; RBAC later)   
- Normalizes requests into internal commands (Upload, Import, Query, Explore)
- Issues signed URLs for large file transfers to object storage
- Tracks requests with correlation IDs for observability
    
This is the primary policy boundary: rate limiting, request validation, and audit logging happen here.

---
## 3) Ingestion and Source Acquisition

Ingestion supports two entry paths that converge into a single pipeline that validates, deduplicates, and schedules each document for downstream processing.
### A. Direct Upload Path

The API gateway obtains a **pre-signed upload URL** from object storage, allowing the client to upload PDFs directly to the **Object Store** (avoids routing large files through the API). After upload, the client notifies the API gateway to register the document.

### B. API Search/Import Path

The UI submits search queries to the API gateway, which calls the **Connector Service**. Connectors integrate with scholarly APIs (e.g., Crossref, Semantic Scholar, arXiv) to:

- Retrieve metadata (title, authors, DOI, abstract)
- Locate a PDF when legally accessible
- Download the PDF into the same object store
- Record provenance: source, query, timestamp, and identifiers

Both paths produce a **Document Registered** event placed onto the **Job Queue** to trigger processing.

Before the event is published, the API gateway calls the **Document Registry Service** to:
- normalize metadata (title casing, author ordering, canonical identifiers)
- compute content hashes and compare DOIs to enforce single-ingest per article
- merge metadata from multiple sources when duplicates are detected
- emit structured errors back to the user if the item already exists or violates size/licensing constraints

The registry persists a canonical row per document in Postgres. Only after deduplication succeeds is the workflow job enqueued, ensuring the downstream pipeline never sees duplicate PDFs and can safely retry idempotently.

### 3.1 Document Registry Service Specification

**Responsibilities**
- Canonical metadata store for every ingestible item
- Deduplication authority using DOI + (hash, title/year) fallback
- Lifecycle state machine (`registered → processing → indexed`) used by the orchestrator
- Retry-safe API that clients can call repeatedly without creating duplicate work

**APIs (all REST over internal network)**
1. `POST /registry/documents`
    - Body: `{doi?, content_hash, title, authors[], journal, year, source, upload_id?, connector_job_id?, user_id}`
    - Behavior: upserts metadata, runs dedup logic, returns canonical `document_id`, status, and next actions (`queued | duplicate | rejected`)
2. `GET /registry/documents/{document_id}`
    - Returns merged metadata, current processing state, provenance entries, and derived artifact pointers.
3. `POST /registry/documents/{document_id}/state`
    - Body: `{state, worker_id, error?}`
    - Used by pipeline stages to advance/retry; enforces valid transitions and emits audit logs.

**Schema Highlights (Postgres)**
- `document_id` (UUID, PK)
- `doi` (unique, nullable)
- `content_hash` (unique index)
- `title`, `subtitle`, `journal`, `year`
- `authors` (JSONB array of `{name, affiliation}`)
- `source_metadata` (JSONB per connector/upload)
- `status` (enum)
- `created_at`, `updated_at`, `last_processed_at`

**Dedup & Retry Semantics**
- Primary dedup key: DOI; fallback: (`content_hash`, `title_normalized`, `year`)
- On duplicate, service merges metadata, stores provenance trail, and returns `{status: "duplicate", existing_document_id}` without enqueueing a job.
- APIs are idempotent: repeated `POST` with same `content_hash` returns the existing row.
- State updates are optimistic: workers include `expected_state` when advancing; mismatches trigger retries with exponential backoff and alerting via the orchestrator.

**Observability**
- Emits structured events (`DocumentRegistered`, `DocumentDuplicate`, `StateTransitionFailed`) with correlation IDs so Ops can trace failures between gateway and workers.

### 3.2 Implementation Plan
1. **DB Migration**
    - Author `registry_documents` table + supporting indexes, enum types, and audit triggers.
    - Seed migration with status enum values and ensure rollback scripts exist.
2. **Service Scaffolding**
    - Spin up a FastAPI (or preferred framework) service with request validation, auth middleware (service token), and structured logging.
    - Implement `POST /registry/documents` first with idempotency keys tied to `content_hash`.
3. **Dedup Logic & Tests**
    - Unit tests covering DOI matches, hash matches, and fuzzy title/year fallback.
    - Integration tests using ephemeral Postgres to verify concurrent requests dedup reliably.
4. **State Machine + Worker Hooks**
    - Define allowed transitions in code; reject invalid sequences with clear error codes for the workflow orchestrator.
    - Add SQS publisher that emits `DocumentRegistered` only on new entries.
5. **Observability & Runbooks**
    - Expose Prometheus metrics (`registry_dedup_hits_total`, `registry_conflicts_total`, latency histograms).
    - Document on-call runbook for reconciliation if registry and vector/graph stores drift.
6. **Rollout**
    - Deploy behind feature flag; shadow-write from API gateway while still enqueuing jobs via legacy path.
    - After validation, flip to registry-as-source-of-truth and remove legacy duplication checks.

---
## 4) Asynchronous Processing Orchestration

A **Workflow Orchestrator** (or a lightweight worker controller) consumes jobs from the queue and coordinates a multi-stage pipeline. Each document is processed idempotently and can be reprocessed on demand.

Pipeline stages are separated so they can scale independently, retry safely, and emit intermediate artifacts:

1. **PDF Parsing**
2. **Text & Structure Extraction**
3. **Chunking & Metadata Enrichment**
4. **Embedding Generation**
5. **Knowledge Extraction & Graph Build**
6. **Index Publishing**

All stage outputs are written to durable stores so failures do not lose progress.

---
## 5) Document Understanding Pipeline

### 5.1 PDF Parsing & Structure Extraction

The **PDF Processing Service** retrieves the PDF from object storage and performs layout-aware extraction:

- Text extraction plus reading order
- Section inference (abstract/methods/results/etc.)
- Table/figure references (captured as metadata in MVP)
- Citation parsing and reference list extraction when possible

Artifacts produced:

- Canonical text (per section)
- Structural map (section boundaries)
- Reference list and in-text citation anchors

### 5.2 Chunking and Canonical Document Model

A **Chunking Service** transforms extracted text into retrieval-optimized units:

- Section-aware chunks with overlap
- Token-length constraints
- Stored alongside metadata: doc_id, section, page range, offsets, DOI, authors, year

Artifacts produced:

- Chunk records suitable for vector indexing
- A searchable “document object model” (DOM-like) representation for provenance

---
## 6) Dual Indexing: Vector Store + Knowledge Graph

### 6.1 Embeddings and Vector Index

The **Embedding Service** generates embeddings for each chunk using a pluggable model. Vectors and metadata are written to the **Vector Database**, enabling:

- Similarity search (cosine or dot-product)
- Metadata filters (year, author, journal, collection)
- Optional hybrid retrieval with keyword signals (phase 1+)

### 6.2 Knowledge Extraction and Graph Build

The **Knowledge Extraction Service** builds a property graph by extracting entities and relations from:
- Full text (or targeted sections)
- Citation structure and references
- Metadata (authors, affiliations, DOI)

Graph components:
- **Nodes:** Article, Author, Entity (concept/method/dataset/instrument)
- **Edges:** cites, authored_by, mentions, uses, related_to (typed)

Each edge includes:
- confidence score
- evidence pointers (chunk_id + offsets)
- timestamps and version info for incremental graph evolution

The graph is stored in a **Graph Database** (Neo4j-compatible property graph), supporting traversals and subgraph retrieval.

---
## 7) Query & RAG Orchestration Layer

The **Query Orchestrator** is responsible for answering user questions with citations and optionally using the knowledge graph to shape retrieval.
### 7.1 Query Understanding

Given a user query, the orchestrator:
- Detects intent: summary, compare, find evidence, trace connections, author/topic exploration
- Extracts constraints: time window, authors, key entities, target papers
- Optionally generates a structured query plan (vector search + graph steps)

### 7.2 Retrieval (Hybrid)

Retrieval proceeds in stages:

1. **Vector Retrieval:** top-K chunks from vector DB
    
2. **Graph Expansion/Filtering (optional):**
    - Expand from entities mentioned in top-K to neighboring nodes
    - Restrict to subgraphs (e.g., “papers connected to dataset X”)
    - Pull supporting chunks tied to graph edges’ evidence
        
3. **Context Assembly:** deduplicate, re-rank, and select best evidence

### 7.3 Generation with Provenance

The **LLM Generation Service** receives:
- Selected chunks + metadata
- Evidence map (chunk_id → doc_id/page/section)
    
- System prompt enforcing citation requirements and abstention when evidence is weak
    
The output includes:
- Final answer
- Cited sources (paper + section + page range)
- Optional “evidence cards” (snippets users can inspect)
    
---
### 7.4 Provenance Contract to the UI

Provenance data flows back to the UI through explicit response payloads:
- **Chat/RAG responses** (`POST /api/query`): `answer`, `citations[]`, and `evidence[]`. Each evidence item carries `chunk_id`, `doc_id`, section, page range, confidence, and a pre-signed URL to the source PDF slice.
- **Streaming updates** (WebSocket `query/{id}`): incremental tokens plus periodic provenance deltas so the UI can show “sources so far.”
- **Graph exploration** (`GET /api/subgraph`): node/edge data plus `evidence_refs[]` keyed by `edge_id`, listing supporting chunk IDs and snippet previews for tooltips.

Frontend requirements:
- Chat view must render inline citation markers that map to the evidence list and open a side panel with the snippet plus “open PDF” action.
- Graph view exposes edge evidence on hover/click and lets users jump to the document detail route preloaded with the same chunk metadata.

These contracts ensure provenance is first-class rather than debug-only, and they align with the transparency commitments in the PRD.
## 8) Graph Exploration and Explainability

The UI’s graph view calls a **Graph API** that returns:
- Node/edge lists for a selected subgraph
- Edge evidence pointers (“why this edge exists”)
- Filters for topic, time, author, confidence threshold

Clicking a node brings the user to:
- Article detail view (metadata, sections, key extracted entities)
- Linked evidence passages used to create relationships

This ensures the graph is not a black box: every relation is traceable to text.

---
## 9) Data Stores and Persistence

The platform uses specialized stores, each with clear responsibilities:

- **Object Store:** raw PDFs and derived artifacts (extracted text JSON, processing outputs)
- **Metadata DB (Postgres):** document registry, user corpora, job status, chunk metadata pointers
- **Vector DB:** embeddings + chunk metadata for similarity retrieval
- **Graph DB:** property graph nodes/edges + evidence pointers
- **Cache (Redis):** session caching, ephemeral query plans, short-lived retrieval results

---
## 10) Observability, Safety, and Operations

### Observability
- Centralized logs with correlation IDs across gateway, workers, and query services
- Metrics: ingestion throughput, processing times, failure rates, query latency
- Tracing across retrieval and generation steps
### Safety & Quality Controls
- Content and prompt injection defenses (strip instructions from retrieved text; enforce system constraints)
- Citation-only mode option (answers must cite sources or abstain)
- Confidence thresholds for relationship publication to graph
- PII redaction policy hooks (mostly relevant for non-journal PDFs later)
### Operational Requirements
- All pipeline stages retry safely and are idempotent
- Reprocessing triggers (per document or per corpus)
- Versioned embeddings/graph schema to support upgrades
