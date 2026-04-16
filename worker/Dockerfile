# ============================================
# StressForge Celery Worker — Multi-Arch Dockerfile
# ============================================
FROM python:3.12-slim

LABEL maintainer="stressforge"
LABEL description="StressForge Celery Background Worker"

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Install backend dependencies (shared with API server)
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy worker code + shared app code
COPY worker/ ./worker/
COPY backend/app/ ./app/

RUN chown -R appuser:appuser /app

USER appuser

# Health check — verify celery is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD celery -A worker.tasks inspect ping --timeout 5 || exit 1

CMD ["celery", "-A", "worker.tasks", "worker", "--loglevel=info", "--concurrency=2", "-Q", "default,orders,reports"]
