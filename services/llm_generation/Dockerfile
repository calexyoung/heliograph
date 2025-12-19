FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy shared modules first (for caching)
COPY shared/ /app/shared/

# Copy service code
COPY services/llm_generation/ /app/services/llm_generation/

# Copy pyproject.toml and README.md for dependencies
COPY pyproject.toml README.md /app/

# Install dependencies
RUN pip install --no-cache-dir -e .

# Set Python path
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8005

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8005/api/v1/health || exit 1

# Run the application
CMD ["uvicorn", "services.llm_generation.app.main:app", "--host", "0.0.0.0", "--port", "8005"]
