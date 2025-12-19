# HelioGraph RAG

Research Intelligence Platform for ingesting PDF journal articles, extracting structured knowledge, building dynamic knowledge graphs, and querying via RAG.

## Quick Start

```bash
# Start all services
docker compose up -d

# Check service health
docker compose ps
```

## Services

- **Document Registry** (port 8000) - Canonical metadata store, deduplication
- **API Gateway** (port 8080) - Auth, routing, rate limiting
- **Ingestion** (port 8002) - PDF upload, external API connectors
- **Document Processing** (port 8003) - PDF parsing, chunking, embeddings
- **Knowledge Extraction** (port 8004) - Entity/relationship extraction
- **Query Orchestrator** (port 8006) - RAG pipeline
- **LLM Generation** (port 8005) - Answer synthesis

## Infrastructure

- PostgreSQL (port 5432)
- Qdrant (port 6333)
- Neo4j (ports 7474, 7687)
- Redis (port 6379)
- LocalStack - S3/SQS (port 4566)
- GROBID (port 8070)
