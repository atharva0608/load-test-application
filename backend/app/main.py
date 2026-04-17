"""
StressForge v3.0 — Main FastAPI Application Entry Point.

A production-grade e-commerce platform designed as an infrastructure
load testing target. Supports CPU, Memory, I/O, and mixed workloads
with tunable intensity for Locust-based load simulation.
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import time
import logging
import uuid
import os

from app.config import get_settings
from app.database import init_db, SessionLocal
from app.seed import seed_products
from app.routers import (
    auth, products, orders, stress, health,
    queue, uptime, cluster, runs,
    metrics_advanced, baseline, admin, stream,
)
from app.circuit_breaker import router as cb_router

# ── Rate Limiting ──
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ── Prometheus ──
from prometheus_fastapi_instrumentator import Instrumentator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("stressforge")

settings = get_settings()

# Rate limiter instance
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    # ── Startup ──
    logger.info(f"🚀 Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    # Initialize database tables
    logger.info("📦 Initializing database...")
    init_db()
    logger.info("✅ Database initialized")

    # Seed products if enabled
    if settings.SEED_ON_STARTUP:
        logger.info(f"🌱 Seeding {settings.SEED_PRODUCTS} products...")
        db = SessionLocal()
        try:
            seed_products(db, settings.SEED_PRODUCTS)
            logger.info("✅ Seed complete")
        except Exception as e:
            logger.error(f"❌ Seed failed: {e}")
        finally:
            db.close()

    logger.info(f"🟢 {settings.APP_NAME} is ready to accept requests")
    yield

    # ── Shutdown ──
    logger.info(f"🔴 Shutting down {settings.APP_NAME}")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="Production-grade infrastructure load testing target application",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — allow all origins for load testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Prometheus instrumentation ──
Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    excluded_handlers=["/api/docs", "/api/redoc", "/api/openapi.json"],
).instrument(app).expose(app, endpoint="/prometheus/metrics")


# ── Request ID + timing + latency tracking + slow request middleware ──
@app.middleware("http")
async def add_request_context(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    start_time = time.time()

    response = await call_next(request)

    duration = time.time() - start_time
    duration_ms = duration * 1000
    status_code = response.status_code
    endpoint = request.url.path

    # Standard headers
    response.headers["X-Response-Time"] = f"{duration:.4f}s"
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Service"] = settings.APP_NAME
    response.headers["X-Pod"] = os.getenv("HOSTNAME", "local")

    # ── Record latency for percentile tracking ──
    try:
        from app.routers.metrics_advanced import record_latency, record_cost_event
        record_latency(endpoint, duration_ms)

        # Record cost events based on request type
        record_cost_event("cpu", duration)  # CPU seconds used
        content_length = int(response.headers.get("content-length", 0))
        record_cost_event("data", content_length)
        if "/api/stress/io" in endpoint or "/api/products" in endpoint or "/api/orders" in endpoint:
            record_cost_event("io", 1)
    except Exception:
        pass

    # ── Record to SSE stream ──
    try:
        from app.routers.stream import record_request
        content_length = int(response.headers.get("content-length", 0))
        record_request(
            status_code=status_code,
            duration_ms=duration_ms,
            endpoint=endpoint,
            request_bytes=int(request.headers.get("content-length", 0)),
            response_bytes=content_length,
        )
    except Exception:
        pass

    # ── Slow request logging ──
    if duration_ms > settings.SLOW_REQUEST_THRESHOLD_MS:
        try:
            from app.routers.metrics_advanced import record_slow_request
            record_slow_request({
                "timestamp": time.time(),
                "endpoint": endpoint,
                "duration_ms": round(duration_ms, 2),
                "db_query_count": 0,  # Would need SQLAlchemy event hooks for real tracking
                "db_total_ms": 0,
                "redis_hit": None,
                "payload_size": int(request.headers.get("content-length", 0)),
                "method": request.method,
            })

            # Push SSE event for slow requests
            from app.routers.stream import push_event
            push_event(
                "slow_request",
                f"Slow request: {request.method} {endpoint} took {duration_ms:.0f}ms",
                "warning",
            )
        except Exception:
            pass

    return response


# ── Register routers ──
# v2.0 routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(stress.router)
app.include_router(queue.router)
app.include_router(queue.jobs_router)
app.include_router(uptime.router)
app.include_router(cluster.router)
app.include_router(runs.router)
app.include_router(cb_router)

# v3.0 routers
app.include_router(metrics_advanced.router)
app.include_router(baseline.router)
app.include_router(admin.router)
app.include_router(stream.router)


# ── Root endpoint ──
@app.get("/")
def root():
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/api/docs",
        "health": "/api/health",
        "stream": "/api/stream",
    }


# ── Global exception handler ──
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    # Push error to SSE stream
    try:
        from app.routers.stream import push_event
        push_event("error", f"Unhandled: {type(exc).__name__}: {str(exc)[:100]}", "error")
    except Exception:
        pass

    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )
