FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy shared modules first (for caching)
COPY shared/ /app/shared/

# Copy service code
COPY services/query_orchestrator/ /app/services/query_orchestrator/

# Copy pyproject.toml and README.md for dependencies
COPY pyproject.toml README.md /app/

# Install dependencies
RUN pip install --no-cache-dir -e ".[processing]"

# Install additional dependencies
RUN pip install --no-cache-dir neo4j tiktoken

# Pre-download sentence-transformers models
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
    SentenceTransformer('all-MiniLM-L6-v2'); \
    CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

# Set Python path
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8006

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8006/api/v1/health || exit 1

# Run the application
CMD ["uvicorn", "services.query_orchestrator.app.main:app", "--host", "0.0.0.0", "--port", "8006"]
