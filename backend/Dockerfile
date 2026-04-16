# ============================================
# StressForge API Server — Multi-Arch Dockerfile
# ============================================
FROM --platform=$BUILDPLATFORM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime ----
FROM python:3.12-slim

# Labels
LABEL maintainer="stressforge"
LABEL description="StressForge API Server"

# Security: non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Copy installed packages
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Own files
RUN chown -R appuser:appuser /app

USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Run with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--log-level", "info"]
