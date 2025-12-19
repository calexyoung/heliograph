# Local Development Guide

This guide covers setting up and running HelioGraph RAG locally for development.

## Prerequisites

- Docker and Docker Compose
- Python 3.11+
- Git

## Quick Start

1. **Clone the repository** (if you haven't already):
   ```bash
   git clone <repository-url>
   cd heliograph
   ```

2. **Run the setup script**:
   ```bash
   ./scripts/setup-local.sh
   ```

3. **Start the Document Registry service**:
   ```bash
   docker-compose up document-registry
   ```

4. **Access the API**:
   - API docs: http://localhost:8000/docs
   - Health check: http://localhost:8000/registry/health

## Manual Setup

If you prefer to set things up manually:

### 1. Environment Configuration

```bash
cp .env.example .env
# Edit .env as needed
```

### 2. Start Infrastructure

```bash
docker-compose up -d postgres redis localstack qdrant neo4j
```

### 3. Run Database Migrations

```bash
# Connect to postgres and run migrations
docker-compose exec postgres psql -U postgres -d heliograph -f /docker-entrypoint-initdb.d/001_create_registry_documents.sql
docker-compose exec postgres psql -U postgres -d heliograph -f /docker-entrypoint-initdb.d/002_create_document_provenance.sql
docker-compose exec postgres psql -U postgres -d heliograph -f /docker-entrypoint-initdb.d/003_create_state_audit_log.sql
```

### 4. Install Python Dependencies

```bash
pip install -e ".[dev]"
```

### 5. Run the Service

```bash
cd services/document-registry
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Service Ports

| Service | Port | Description |
|---------|------|-------------|
| Document Registry | 8000 | API + Metrics |
| PostgreSQL | 5432 | Database |
| Redis | 6379 | Cache |
| Qdrant | 6333, 6334 | Vector DB (HTTP, gRPC) |
| Neo4j | 7474, 7687 | Graph DB (Browser, Bolt) |
| LocalStack | 4566 | S3/SQS emulation |
| Prometheus | 9090 | Metrics (optional) |
| Grafana | 3001 | Dashboards (optional) |

## Running Tests

### Unit Tests

```bash
pytest services/document-registry/tests/ -v
```

### With Coverage

```bash
pytest services/document-registry/tests/ --cov=services/document-registry/app --cov-report=html
```

### Integration Tests

Integration tests require running infrastructure:

```bash
docker-compose up -d postgres localstack
pytest services/document-registry/tests/integration/ -v
```

## API Usage Examples

### Register a Document

```bash
curl -X POST http://localhost:8000/registry/documents \
  -H "Content-Type: application/json" \
  -d '{
    "content_hash": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
    "title": "Solar Flare Analysis Study",
    "source": "upload",
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "doi": "10.1234/solar.2024.001",
    "authors": [
      {"given_name": "John", "family_name": "Doe"}
    ],
    "year": 2024
  }'
```

### Get Document Details

```bash
curl http://localhost:8000/registry/documents/{document_id}
```

### Transition Document State

```bash
curl -X POST http://localhost:8000/registry/documents/{document_id}/state \
  -H "Content-Type: application/json" \
  -d '{
    "state": "processing",
    "worker_id": "worker-1"
  }'
```

## Observability

### Enable Prometheus and Grafana

```bash
docker-compose --profile observability up -d prometheus grafana
```

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001 (admin/admin)

### View Metrics

```bash
curl http://localhost:8000/metrics
```

## Troubleshooting

### Database Connection Issues

```bash
# Check if postgres is running
docker-compose ps postgres

# View postgres logs
docker-compose logs postgres
```

### LocalStack Issues

```bash
# Check if S3 bucket exists
aws --endpoint-url=http://localhost:4566 s3 ls

# Check if SQS queue exists
aws --endpoint-url=http://localhost:4566 sqs list-queues
```

### Reset Everything

```bash
docker-compose down -v
./scripts/setup-local.sh
```

## Development Workflow

1. Create a feature branch
2. Make changes
3. Run tests: `pytest`
4. Run linting: `ruff check .`
5. Run type checking: `mypy services/document-registry/app`
6. Format code: `black .`
7. Commit and push
