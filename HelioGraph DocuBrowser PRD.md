
## Product Name (Working)
HelioGraph RAG

---
## Product Overview

HelioGraph RAG is a web-based research intelligence platform that enables users to ingest PDF journal articles—either by direct upload or via external scholarly APIs—automatically extract structured knowledge, build dynamic knowledge graphs, and query the resulting corpus using Retrieval-Augmented Generation (RAG). The MVP prioritizes rapid ingestion, transparent provenance, and graph-aware querying.  (an example service that provides some of these features would be Google's NotebookLM though that product provides unnecessary features like videos and podcast and does not provide a API ingestion capability and it is not open source, only working through Google)

---
## Target Users

- Heliophysics/Astrophysics Researchers and scientists
- Policy analysts and technical staff
- Graduate students and educators
- R&D teams managing large literature corpora

--
## Core MVP Capabilities
### 1. Document Ingestion
**Upload**
- Drag-and-drop PDF upload (single or batch)
- Automatic metadata extraction (title, authors, journal, year, DOI)

**API-Based Discovery**
- Search and import articles via APIs (e.g., SciXplorer, arXiv)
- PDF retrieval when legally accessible
- De-duplication via DOI and content hashing
    
---
### 2. Document Processing Pipeline
- PDF text extraction (layout-aware)
- Section segmentation (abstract, methods, results, conclusions)
- Chunking optimized for embeddings
- Embedding generation using a configurable embedding model
- Vector storage in a scalable vector database

---
### 3. Knowledge Extraction & Graph Construction

**Entity & Relationship Extraction**
- Key entities: concepts, methods, instruments, datasets, authors, institutions
- Relationships: _uses_, _extends_, _contradicts_, _measures_, _authored_by_, _cites_

**Knowledge Graph**
- Graph nodes: articles, entities, authors
- Graph edges derived from citations and semantic relationships
- Stored in a graph database (e.g., Neo4j-compatible)
    
**Graph Updates**
- Incremental updates as new documents are added
- Versioned graph snapshots

---
### 4. RAG-Based Query Interface

- Natural-language question answering over the corpus
- Hybrid retrieval:
    - Vector similarity search    
    - Graph-aware filtering (e.g., “methods connected to dataset X”)
- Answers include:
    - Synthesized response
    - Source citations (article + section)
    - Confidence/coverage indicators

---
### 5. Knowledge Graph Exploration UI

- Interactive graph visualization
- Filter by article, author, concept, or year
- Click-through from graph nodes to source text
- Highlight supporting passages for relationships

---
### 6. Provenance & Transparency

- Every answer linked to source documents
- Ability to inspect retrieved chunks
- Clear separation between extracted facts and generated synthesis
- Chat experience requirements:
    - Inline citation markers are tappable and open a right-hand evidence panel that lists snippet text, chunk metadata (doc, page, section), and “open PDF to page” action.
    - Streaming responses show a “sources so far” rail fed by WebSocket provenance deltas; tapping a source freezes the stream and focuses its evidence card.
- Graph experience requirements:
    - Selecting an edge highlights the supporting evidence card(s) supplied by the Graph API, including snippet preview, confidence score, and jump-to-document control.
    - Document detail pages deep-link to specific chunk IDs so users land directly on the cited passage regardless of entry point.
- UX/Design delivers annotated mocks covering the citation panel, graph edge tooltip, and document detail deep link before implementation begins to ensure alignment with the backend contracts.
- Design deliverables:
    - Wireframes (lo-fi) due Week 4 for chat citation rail + graph edge evidence tooltip.
    - Hi-fi mocks + interaction specs due Week 6, followed by a cross-team review (Design + Backend + Frontend) to confirm API payload coverage.
    - Prototype in Figma/Framer demonstrating streaming “sources so far” behavior prior to frontend implementation kickoff.
- **Design Sprint Kickoff**
    - Sprint Duration: Weeks 3–6 of the MVP timeline.
    - Sprint Goals: deliver lo-fi wireframes (Week 4), hi-fi mocks + interaction specs (Week 6), and clickable prototype (Week 6).
    - Rituals:
        - Sprint Planning (Week 3 Monday) with Design, Backend, Frontend leads to confirm scope and API touchpoints.
        - Mid-sprint Critique (Week 4 Wednesday) to review wireframes against provenance requirements.
        - Final Review (Week 6 Thursday) to sign off on hi-fi mocks/prototype and log any engineering follow-ups.
    - Outputs are stored in the shared design drive with versioned links referenced in engineering tickets.

---
### 7. Open Source Stack, Local and Remote Deployment

- The stack must be open source with no institutional cost
- It should be implementable locally or using internal resources based on the AWS cloud services.
- Scalable

---
## Non-Goals for MVP

- Full ontology management
- Automated hypothesis generation
- Real-time collaborative editing
- Fine-grained access control beyond basic user accounts

---
## Technical Architecture (High-Level)

- Frontend: Web UI (upload, search, graph view, chat)
- Backend:
    
    - PDF processing service  
    - Embedding & vector store
    - Graph database
    - RAG orchestration layer
- LLM: Pluggable (cloud or self-hosted)
- Storage: Object store for PDFs + metadata DB

---

## Success Criteria for MVP

- User can ingest ≥50 PDFs with minimal manual intervention
- Knowledge graph visibly connects articles via shared concepts and citations
- Users can ask complex, cross-paper questions and receive cited answers
- Graph updates automatically when new documents are added
- End-to-end ingest turnaround (upload → searchable) averages ≤10 minutes with P95 ≤20 minutes for 20-page PDFs
- RAG responses, including citations, render in ≤8 seconds P95 for queries over 1k documents
- Graph visualization loads and becomes interactive in ≤3 seconds for subgraphs up to 200 nodes
- Provenance UI surfaces chunk-level evidence with working “open source passage” links in both chat and graph views
- All components rely on OSI-approved, locally deployable dependencies; third-party licenses and minimum hardware profiles are documented
- Performance SLAs are reviewed and signed off in a joint Engineering/Infra readiness doc that lists the supporting hardware profile (CPU/GPU/memory), expected workload mix, and any mitigation plans if benchmarks fall short

---
# Technical Requirements

## 1. System Architecture Requirements

### 1.1 Frontend

- Web-based UI (React or equivalent)
- Secure authentication (OAuth or email-based)
- Core views:
    - Document upload & API search
    - Corpus overview (documents, metadata)
    - RAG query/chat interface
    - Knowledge graph visualization
- Responsive design for desktop-first use

---
### 1.2 Backend Services

#### API Layer
- REST + WebSocket endpoints
- Stateless request handling
- Rate limiting and request logging
#### Ingestion Service
- PDF upload handling (single/batch)
- API connectors (Crossref, Semantic Scholar, arXiv)
- File hashing + DOI-based deduplication
- Persistent raw PDF storage

#### Document Processing Pipeline
- Layout-aware text extraction (e.g., PDFMiner, GROBID)
- Section classification (abstract, methods, etc.)
- Chunking with overlap and section metadata
- Language detection (English-first MVP)

#### Embedding & Retrieval
- Pluggable embedding models
- Vector database with:
    - cosine similarity  
    - metadata filtering    
- Hybrid retrieval support (vector + graph constraints)

---
### 1.3 Knowledge Extraction & Graph

#### Entity Extraction
- Named entity recognition for:
    - concepts 
    - methods    
    - datasets
    - instruments
    - authors & institutions
- Citation parsing and linking
#### Relationship Extraction
- LLM-assisted relation classification
- Typed edges with confidence scores
#### Graph Storage
- Property graph database
- Nodes:
    - Article
    - Entity    
    - Author 
- Edges:
    - cites    
    - uses
    - authored_by
    - related_to

---
### 1.4 RAG Orchestration

- Retrieval pipeline:
    1. Query parsing
    2. Vector retrieval
    3. Graph-based filtering/expansion
    4. Context assembly
        
- Answer generation with:
    - citation tracking
    - chunk-level provenance
- Configurable prompt templates
    
---
### 1.5 Observability & Ops
- Structured logging
- Pipeline failure reporting
- Basic usage analytics
- Manual reprocessing triggers
# Phased Roadmap Beyond MVP

---
## Phase 0 — MVP (Baseline Capability)

**Goal:** Functional RAG + graph system for individual researchers.
- PDF upload and API-based ingestion
- Basic entity and citation graph
- Natural-language RAG queries
- Interactive graph visualization
- Source-cited answers

---
## Phase 1 — Graph Intelligence & Query Power

**Goal:** Move from “chat over papers” to “reasoning over literature.”
**Key Additions**
- Graph-aware query language (NL → graph constraints)
- Multi-hop graph reasoning
- Relationship confidence scoring and filtering
- Temporal graph views (evolution of ideas)
- “Why is this connected?” explanations

**User Value**
- Understand how ideas propagate across papers
- Identify influential methods and datasets

---
## Phase 2 — Corpus Management & Curation

**Goal:** Support larger, evolving document collections.
**Key Additions**
- Topic clustering and auto-tagging
- Document versioning
- Corpus-level summaries
- User-defined collections and scopes
- Quality signals (citation count, recency)

**User Value**
- Maintain living literature reviews
- Reduce noise in large corpora

---
## Phase 3 — Advanced Knowledge Graphs
**Goal:** Transition from extracted facts to structured scientific knowledge.
**Key Additions**
- Ontology alignment (optional domain schemas)
- Claim extraction (hypotheses, findings)
- Contradiction and agreement detection
- Evidence-weighted edges
- Cross-corpus graph linking

**User Value**
- Compare competing results
- Identify gaps and conflicts in the literature

---
## Phase 4 — Collaboration & Organizational Use

**Goal:** Enable team-based and institutional deployments.

**Key Additions**
- Role-based access control
- Shared corpora and graphs
- Annotation and commenting
- Export to reports and briefs
- API access for downstream tools
    
**User Value**
- Institutional memory for research groups
- Policy and decision-support workflows
    
---
## Phase 5 — Automation & Discovery

**Goal:** Proactive, insight-generating research assistant.

**Key Additions**
- Automated literature monitoring
- Alerting on new relevant papers
- Trend detection across the graph
- Hypothesis and question suggestion
- Integration with notebooks and IDEs

**User Value**
- Continuous awareness
- Faster discovery and synthesis
