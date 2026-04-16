"""
StressForge Health Router — Liveness + Readiness probes.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.config import get_settings
from app.schemas import HealthResponse, ReadinessResponse
from app.crud import get_product_count, get_user_count, get_order_count
import time
import redis
import psutil

settings = get_settings()
router = APIRouter(prefix="/api", tags=["Health"])

_start_time = time.time()


@router.get("/health", response_model=HealthResponse)
def health_check():
    """Liveness probe — lightweight, no external dependencies."""
    return HealthResponse(
        status="healthy",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        uptime_seconds=round(time.time() - _start_time, 2),
    )


@router.get("/health/ready", response_model=ReadinessResponse)
def readiness_check(db: Session = Depends(get_db)):
    """Readiness probe — checks DB and Redis connectivity."""
    db_status = "disconnected"
    redis_status = "disconnected"
    details = {}

    # Check PostgreSQL
    try:
        result = db.execute(text("SELECT 1"))
        result.fetchone()
        db_status = "connected"
    except Exception as e:
        details["db_error"] = str(e)

    # Check Redis
    try:
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.ping()
        redis_status = "connected"
        r.close()
    except Exception as e:
        details["redis_error"] = str(e)

    overall = "ready" if db_status == "connected" and redis_status == "connected" else "not_ready"

    return ReadinessResponse(
        status=overall,
        database=db_status,
        redis=redis_status,
        details=details if details else None,
    )


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)):
    """Prometheus-style metrics endpoint."""
    try:
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        redis_info = r.info("memory")
        redis_memory = redis_info.get("used_memory_human", "N/A")
        redis_keys = r.dbsize()
        r.close()
    except Exception:
        redis_memory = "N/A"
        redis_keys = 0

    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "uptime_seconds": round(time.time() - _start_time, 2),
        "database": {
            "users": get_user_count(db),
            "products": get_product_count(db),
            "orders": get_order_count(db),
        },
        "redis": {
            "memory": redis_memory,
            "keys": redis_keys,
        },
    }

@router.get("/metrics/system")
def system_metrics():
    """Live system gauges via psutil."""
    cpu_percent = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()
    net = psutil.net_io_counters()

    # Calculate network usage safely if historical data is needed in future
    return {
        "cpu_percent": cpu_percent,
        "ram_percent": memory.percent,
        "ram_used_mb": memory.used // (1024 * 1024),
        "ram_total_mb": memory.total // (1024 * 1024),
        "net_sent_mb": net.bytes_sent // (1024 * 1024),
        "net_recv_mb": net.bytes_recv // (1024 * 1024)
    }

