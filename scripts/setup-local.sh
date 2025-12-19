#!/bin/bash
# Local development setup script for HelioGraph RAG

set -e

echo "=== HelioGraph RAG Local Setup ==="
echo ""

# Check for required tools
check_command() {
    if ! command -v $1 &> /dev/null; then
        echo "Error: $1 is required but not installed."
        exit 1
    fi
}

echo "Checking required tools..."
check_command docker
check_command docker-compose
check_command python3

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
fi

# Make localstack init script executable
chmod +x scripts/localstack-init.sh

# Start infrastructure services
echo ""
echo "Starting infrastructure services..."
docker-compose up -d postgres redis localstack qdrant neo4j

echo "Waiting for services to be ready..."
sleep 10

# Run database migrations
echo ""
echo "Running database migrations..."
for migration in services/document-registry/migrations/*.sql; do
    echo "  Applying: $migration"
    docker-compose exec -T postgres psql -U postgres -d heliograph -f /docker-entrypoint-initdb.d/$(basename $migration)
done

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip install -e ".[dev]"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Available services:"
echo "  - PostgreSQL:       localhost:5432"
echo "  - Redis:            localhost:6379"
echo "  - Qdrant:           localhost:6333"
echo "  - Neo4j:            localhost:7474 (browser), :7687 (bolt)"
echo "  - LocalStack (S3):  localhost:4566"
echo ""
echo "To start the Document Registry service:"
echo "  docker-compose up document-registry"
echo ""
echo "Or run locally:"
echo "  cd services/document-registry"
echo "  uvicorn app.main:app --reload"
echo ""
echo "To run tests:"
echo "  pytest services/document-registry/tests/"
echo ""
echo "To view metrics (requires --profile observability):"
echo "  docker-compose --profile observability up prometheus grafana"
