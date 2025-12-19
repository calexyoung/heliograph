# Document Registry Service Dockerfile
# Multi-stage build for optimized image size

# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml README.md /app/
RUN pip install --no-cache-dir build && \
    pip wheel --no-cache-dir --wheel-dir /app/wheels -e .

# Runtime stage
FROM python:3.11-slim as runtime

WORKDIR /app

# Create non-root user
RUN groupadd -r heliograph && useradd -r -g heliograph heliograph

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy wheels and install
COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# Copy application code
COPY shared/ /app/shared/
COPY services/document_registry/ /app/services/document_registry/

# Set Python path
ENV PYTHONPATH=/app

# Change ownership to non-root user
RUN chown -R heliograph:heliograph /app

USER heliograph

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/registry/health', timeout=5)" || exit 1

# Run the application
CMD ["uvicorn", "services.document_registry.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
