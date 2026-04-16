"""
StressForge — Main FastAPI Application Entry Point.

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

from app.config import get_settings
from app.database import init_db, SessionLocal
from app.seed import seed_products
from app.routers import auth, products, orders, stress, health

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("stressforge")

settings = get_settings()


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

# CORS — allow all origins for load testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request timing middleware ──
@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    response.headers["X-Response-Time"] = f"{duration:.4f}s"
    response.headers["X-Service"] = settings.APP_NAME
    return response


# ── Register routers ──
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(stress.router)


# ── Root endpoint ──
@app.get("/")
def root():
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/api/docs",
        "health": "/api/health",
    }


# ── Global exception handler ──
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )
