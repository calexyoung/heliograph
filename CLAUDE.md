# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HelioGraph RAG is a web-based research intelligence platform for ingesting PDF journal articles, extracting structured knowledge, building dynamic knowledge graphs, and querying via RAG. Primary users are heliophysics/astrophysics researchers.

**Current Status:** Planning phase - no code implementation yet. See planning documents for requirements and architecture.

## Planning Documents

- `HelioGraph DocuBrowser PRD.md` - Product requirements, MVP capabilities, phased roadmap
- `Technical Architecture Narrative - HelioGraph.md` - System architecture, data flows, component specifications
- `Document Registry Workstream Plan.md` - Implementation plan for the first backend service
- `Eng-Infra Readiness.md` - Hardware profiles, SLA targets, validation plans

## Tech Stack

**Backend:** FastAPI services with Pydantic models for API contracts. Python.
**Frontend:** React web UI.
**Data Stores:** Postgres (registry/metadata), Qdrant (vectors), Neo4j (graph), S3 (PDFs/artifacts), Redis (cache).
**Queue:** SQS for async workflow orchestration.
**PDF Processing:** GROBID or PDFMiner for layout-aware extraction.

## Architecture

The system has two ingestion paths that converge:
1. **Direct Upload:** Client uploads PDF to S3 via pre-signed URL, then registers with API gateway
2. **API Import:** Connectors (Crossref, Semantic Scholar, arXiv) fetch metadata and PDFs

Both paths → Document Registry Service (dedup) → SQS `DocumentRegistered` event → Processing Pipeline.

**Backend Services:**
- API Gateway/BFF - Auth (OAuth), routing, rate limiting, correlation IDs
- Document Registry Service - Canonical metadata store, deduplication, lifecycle state machine
- Ingestion Service - PDF upload handling, external API connectors
- Document Processing Pipeline - PDF parsing, section segmentation, chunking, embeddings
- Knowledge Extraction Service - Entity/relationship extraction, graph construction
- Query Orchestrator - RAG pipeline with hybrid retrieval (vector + graph)
- LLM Generation Service - Answer synthesis with citations

**Processing Pipeline Stages:** PDF Parsing → Text/Structure Extraction → Chunking → Embedding Generation → Knowledge Extraction → Index Publishing

## First Implementation Target: Document Registry Service

The Document Registry Service is the first backend component to implement.

**APIs:**
- `POST /registry/documents` - Upsert metadata, run dedup, return canonical `document_id` and status (`queued | duplicate | rejected`)
- `GET /registry/documents/{document_id}` - Return metadata, processing state, provenance, artifact pointers
- `POST /registry/documents/{document_id}/state` - Advance lifecycle state (used by pipeline workers)

**Database Schema (`registry_documents`):**
- `document_id` (UUID PK), `doi` (unique nullable), `content_hash` (unique index)
- `title`, `subtitle`, `journal`, `year`, `authors` (JSONB array)
- `source_metadata` (JSONB), `status` (enum: registered/processing/indexed)
- `created_at`, `updated_at`, `last_processed_at`

**Dedup Logic:** Primary key is DOI; fallback is (`content_hash`, `title_normalized`, `year`). Fuzzy title matching uses Levenshtein ratio threshold 0.9.

**Key Metrics:** `registry_dedup_hits_total`, `registry_conflicts_total`, latency histograms.

## Key Design Principles

- All pipeline stages are idempotent and retriable
- Every graph relationship is traceable to source text (chunk_id + offsets)
- Answers must cite sources or abstain
- APIs use idempotency keys tied to `content_hash`
- State transitions are optimistic with `expected_state` checks and exponential backoff
- Open source stack, deployable locally (12-core/64GB/RTX 4090) or on AWS

## Performance SLAs (MVP)

- Ingest turnaround: ≤10 min avg, ≤20 min P95 (20-page PDF)
- RAG response: ≤8s P95 for corpora up to 1k docs
- Graph render: ≤3s to interactive for ≤200-node subgraphs
