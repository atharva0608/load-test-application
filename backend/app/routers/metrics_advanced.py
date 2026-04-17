"""
StressForge — Advanced Metrics Router.
DB pool status, pod age, latency percentiles, cost estimation, slow requests.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
import time
import os
import collections
import threading

from app.database import get_db, engine

router = APIRouter(prefix="/api/metrics", tags=["metrics-advanced"])

# ── In-memory latency histogram ──────────────────────
# Thread-safe latency tracking per endpoint
_latency_lock = threading.Lock()
_latency_data: Dict[str, List[float]] = collections.defaultdict(list)
_latency_max_points = 10000  # Per endpoint

# Cost tracking
_cost_lock = threading.Lock()
_cost_accumulator = {
    "cpu_seconds": 0.0,
    "io_operations": 0,
    "data_transfer_bytes": 0,
    "celery_tasks": 0,
    "session_start": time.time(),
}

# Slow request buffer
_slow_requests_lock = threading.Lock()
_slow_requests: List[dict] = []
_slow_requests_max = 500

# Pod start time
POD_START_TIME = time.time()

# Cache hit tracking
_cache_stats = {"hits": 0, "misses": 0}


def record_latency(endpoint: str, duration_ms: float):
    """Called by middleware to record per-endpoint latency."""
    with _latency_lock:
        bucket = _latency_data[endpoint]
        bucket.append(duration_ms)
        if len(bucket) > _latency_max_points:
            _latency_data[endpoint] = bucket[-_latency_max_points:]


def record_slow_request(entry: dict):
    """Called by middleware for requests > threshold."""
    with _slow_requests_lock:
        _slow_requests.append(entry)
        if len(_slow_requests) > _slow_requests_max:
            _slow_requests.pop(0)


def record_cost_event(event_type: str, amount: float = 1.0):
    """Accumulate cost events."""
    with _cost_lock:
        if event_type == "cpu":
            _cost_accumulator["cpu_seconds"] += amount
        elif event_type == "io":
            _cost_accumulator["io_operations"] += int(amount)
        elif event_type == "data":
            _cost_accumulator["data_transfer_bytes"] += int(amount)
        elif event_type == "celery":
            _cost_accumulator["celery_tasks"] += int(amount)


def record_cache_event(hit: bool):
    """Track cache hit/miss for cold start analysis."""
    if hit:
        _cache_stats["hits"] += 1
    else:
        _cache_stats["misses"] += 1


# ── Schemas ──────────────────────────────────────────

class PoolStatus(BaseModel):
    pool_size: int
    checked_out: int
    overflow: int
    checked_in: int
    max_overflow: int
    pool_timeout: int
    status_summary: str


class PodAge(BaseModel):
    pod_name: str
    uptime_seconds: float
    cache_hit_rate: float
    cache_hits: int
    cache_misses: int
    connections_established: int
    warm: bool


class PercentileEntry(BaseModel):
    endpoint: str
    p50: float
    p95: float
    p99: float
    p999: float
    count: int
    min_ms: float
    max_ms: float


class CostEstimate(BaseModel):
    session_duration_seconds: float
    cost_per_hour_usd: float
    cost_per_month_usd: float
    cost_per_year_usd: float
    breakdown: Dict[str, float]
    total_events: Dict[str, int]


class SlowRequestEntry(BaseModel):
    timestamp: float
    endpoint: str
    duration_ms: float
    db_query_count: int
    db_total_ms: float
    redis_hit: Optional[bool]
    payload_size: int
    method: str


# ── Endpoints ────────────────────────────────────────

@router.get("/db-pool", response_model=PoolStatus)
def get_db_pool_status():
    """Returns current SQLAlchemy connection pool status."""
    pool = engine.pool
    checked_out = pool.checkedout()
    checked_in = pool.checkedin()
    overflow_val = pool.overflow()
    pool_sz = pool.size()

    total_capacity = pool_sz + pool._max_overflow
    utilization = checked_out / total_capacity * 100 if total_capacity > 0 else 0

    if utilization > 90:
        summary = "CRITICAL — pool nearly exhausted"
    elif utilization > 70:
        summary = "WARNING — pool under pressure"
    elif utilization > 40:
        summary = "MODERATE — healthy utilization"
    else:
        summary = "HEALTHY — pool has capacity"

    return PoolStatus(
        pool_size=pool_sz,
        checked_out=checked_out,
        overflow=overflow_val,
        checked_in=checked_in,
        max_overflow=pool._max_overflow,
        pool_timeout=int(pool._timeout),
        status_summary=summary,
    )


@router.get("/pod-age", response_model=PodAge)
def get_pod_age():
    """Returns pod startup time, cache performance, and warm-up status."""
    uptime = time.time() - POD_START_TIME
    total_cache = _cache_stats["hits"] + _cache_stats["misses"]
    hit_rate = (_cache_stats["hits"] / total_cache * 100) if total_cache > 0 else 0.0

    pool = engine.pool
    conns = pool.checkedout() + pool.checkedin()

    return PodAge(
        pod_name=os.getenv("HOSTNAME", "local"),
        uptime_seconds=round(uptime, 1),
        cache_hit_rate=round(hit_rate, 2),
        cache_hits=_cache_stats["hits"],
        cache_misses=_cache_stats["misses"],
        connections_established=conns,
        warm=uptime > 60 and hit_rate > 50,
    )


@router.get("/latency-percentiles", response_model=List[PercentileEntry])
def get_latency_percentiles():
    """Returns p50/p95/p99/p99.9 per endpoint from in-memory histogram."""
    results = []
    with _latency_lock:
        for endpoint, values in _latency_data.items():
            if not values:
                continue
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            results.append(PercentileEntry(
                endpoint=endpoint,
                p50=sorted_vals[int(n * 0.50)] if n > 0 else 0,
                p95=sorted_vals[int(n * 0.95)] if n > 1 else sorted_vals[-1],
                p99=sorted_vals[int(n * 0.99)] if n > 2 else sorted_vals[-1],
                p999=sorted_vals[min(int(n * 0.999), n - 1)] if n > 0 else 0,
                count=n,
                min_ms=sorted_vals[0],
                max_ms=sorted_vals[-1],
            ))
    results.sort(key=lambda x: x.p99, reverse=True)
    return results


@router.get("/cost-estimate", response_model=CostEstimate)
def get_cost_estimate():
    """Returns running AWS cost simulation for current session."""
    # AWS cost rates (approximate t3.medium / gp3 / standard)
    CPU_COST_PER_HOUR = float(os.getenv("COST_CPU_PER_HOUR", "0.0416"))
    IOPS_COST_PER_1000 = float(os.getenv("COST_IOPS_PER_1000", "0.005"))
    DATA_PER_GB = float(os.getenv("COST_DATA_PER_GB", "0.09"))
    CELERY_COST_PER_1000 = float(os.getenv("COST_CELERY_PER_1000", "0.02"))

    with _cost_lock:
        elapsed = time.time() - _cost_accumulator["session_start"]
        hours = elapsed / 3600

        compute_cost = ((_cost_accumulator["cpu_seconds"] / 3600) * CPU_COST_PER_HOUR)
        io_cost = (_cost_accumulator["io_operations"] / 1000) * IOPS_COST_PER_1000
        data_cost = (_cost_accumulator["data_transfer_bytes"] / (1024**3)) * DATA_PER_GB
        celery_cost = (_cost_accumulator["celery_tasks"] / 1000) * CELERY_COST_PER_1000

        # Base infra cost (running pods, DB, Redis regardless of load)
        base_cost = hours * 0.15  # ~$0.15/hr for base infra

        total_per_hour = (compute_cost + io_cost + data_cost + celery_cost + base_cost) / max(hours, 0.001)

    return CostEstimate(
        session_duration_seconds=round(elapsed, 1),
        cost_per_hour_usd=round(total_per_hour, 4),
        cost_per_month_usd=round(total_per_hour * 730, 2),
        cost_per_year_usd=round(total_per_hour * 8760, 2),
        breakdown={
            "compute_ec2": round(compute_cost, 6),
            "storage_iops": round(io_cost, 6),
            "data_transfer": round(data_cost, 6),
            "celery_workers": round(celery_cost, 6),
            "base_infrastructure": round(base_cost, 6),
        },
        total_events={
            "cpu_seconds": int(_cost_accumulator["cpu_seconds"]),
            "io_operations": _cost_accumulator["io_operations"],
            "data_transfer_bytes": _cost_accumulator["data_transfer_bytes"],
            "celery_tasks": _cost_accumulator["celery_tasks"],
        },
    )


@router.get("/slow-requests", response_model=List[SlowRequestEntry])
def get_slow_requests(limit: int = 100):
    """Returns recent slow requests (>1000ms) with full context."""
    with _slow_requests_lock:
        return _slow_requests[-limit:]
