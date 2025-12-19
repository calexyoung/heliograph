FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy shared modules first (for caching)
COPY shared/ /app/shared/

# Copy service code
COPY services/ingestion/ /app/services/ingestion/

# Copy pyproject.toml and README.md for dependencies
COPY pyproject.toml README.md /app/

# Install dependencies
RUN pip install --no-cache-dir -e ".[ingestion]"

# Set Python path
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8002/api/v1/health || exit 1

# Run the application
CMD ["uvicorn", "services.ingestion.app.main:app", "--host", "0.0.0.0", "--port", "8002"]
