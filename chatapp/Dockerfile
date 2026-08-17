# HTMX ChatApp Dockerfile
# Python 3.11 base image for FastAPI application
# Using ECR Public to avoid Docker Hub rate limits

FROM public.ecr.aws/docker/library/python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8080

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
# Retry on transient PyPI/CDN failures (e.g. 502s from files.pythonhosted.org).
# pip's own --retries back off in under a second, so they cannot ride out even a
# brief outage; the outer loop adds escalating sleeps. A genuine failure still
# exits non-zero rather than producing an image with missing dependencies.
RUN for i in 1 2 3 4 5; do \
        pip install --no-cache-dir --retries 10 --timeout 30 -r requirements.txt && break; \
        if [ "$i" = 5 ]; then echo "pip install failed after 5 attempts"; exit 1; fi; \
        echo "pip install attempt $i failed; retrying in $((i * 15))s"; \
        sleep $((i * 15)); \
    done

# Copy application code
COPY app/ ./app/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run uvicorn server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
