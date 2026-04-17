"""
StressForge — SSE (Server-Sent Events) Streaming Router.
Single endpoint that pushes live system telemetry every 1 second.
This is the backbone of the real-time dashboard.
"""
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
import asyncio
import time
import os
import json
import logging
import psutil
import collections
import threading

from app.database import engine

router = APIRouter(prefix="/api", tags=["stream"])
logger = logging.getLogger("stressforge.stream")

# ── Shared event bus ──────────────────────────────────
# Events from chaos, alerts, scaling — pushed to all SSE clients
_event_lock = threading.Lock()
_event_buffer: collections.deque = collections.deque(maxlen=500)
_active_connections = 0


def push_event(event_type: str, message: str, severity: str = "info"):
    """Push an event to all SSE clients."""
    with _event_lock:
        _event_buffer.append({
            "timestamp": time.time(),
            "type": event_type,
            "message": message,
            "severity": severity,  # info, warning, error, success
        })


def get_recent_events(since: float = 0, limit: int = 50) -> list:
    """Get events since a timestamp."""
    with _event_lock:
        return [e for e in _event_buffer if e["timestamp"] > since][-limit:]


# ── RPS / Error tracking (updated by middleware) ─────
_rps_lock = threading.Lock()
_request_window: collections.deque = collections.deque(maxlen=10000)  # (timestamp, status_code, duration_ms, endpoint)
_throughput_bytes = {"in": 0, "out": 0}


def record_request(status_code: int, duration_ms: float, endpoint: str, request_bytes: int = 0, response_bytes: int = 0):
    """Called by middleware for every request."""
    with _rps_lock:
        _request_window.append((time.time(), status_code, duration_ms, endpoint))
        _throughput_bytes["in"] += request_bytes
        _throughput_bytes["out"] += response_bytes


def _compute_rps_stats(window_seconds: int = 5):
    """Compute RPS and error rate from recent window."""
    now = time.time()
    cutoff = now - window_seconds

    with _rps_lock:
        recent = [(t, sc, d, e) for t, sc, d, e in _request_window if t > cutoff]

    if not recent:
        return {"rps": 0, "error_rate": 0, "p50": 0, "p95": 0, "p99": 0, "p999": 0, "total": 0}

    durations = sorted([d for _, _, d, _ in recent])
    errors = sum(1 for _, sc, _, _ in recent if sc >= 400)
    n = len(durations)

    return {
        "rps": round(n / window_seconds, 1),
        "error_rate": round(errors / n * 100, 2) if n > 0 else 0,
        "p50": durations[int(n * 0.50)] if n > 0 else 0,
        "p95": durations[int(n * 0.95)] if n > 1 else durations[-1] if durations else 0,
        "p99": durations[int(n * 0.99)] if n > 2 else durations[-1] if durations else 0,
        "p999": durations[min(int(n * 0.999), n - 1)] if n > 0 else 0,
        "total": n,
    }


def _get_system_metrics():
    """Collect system-level metrics."""
    try:
        cpu = psutil.cpu_percent(interval=0)
        mem = psutil.virtual_memory()
        return {
            "cpu_percent": cpu,
            "ram_percent": mem.percent,
            "ram_used_mb": round(mem.used / (1024 * 1024)),
            "ram_total_mb": round(mem.total / (1024 * 1024)),
        }
    except Exception:
        return {"cpu_percent": 0, "ram_percent": 0, "ram_used_mb": 0, "ram_total_mb": 0}


def _get_pool_stats():
    """Get DB connection pool stats."""
    try:
        pool = engine.pool
        return {
            "pool_size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "checked_in": pool.checkedin(),
        }
    except Exception:
        return {"pool_size": 0, "checked_out": 0, "overflow": 0, "checked_in": 0}


def _get_queue_depth():
    """Quick Redis check for Celery queue depth."""
    try:
        import redis
        r = redis.from_url(os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1"))
        queues = ["default", "high_priority", "medium_priority", "low_priority", "celery_dead_letter"]
        depths = {}
        total = 0
        for q in queues:
            length = r.llen(q)
            depths[q] = length
            total += length
        r.close()
        return {"total": total, "queues": depths}
    except Exception:
        return {"total": 0, "queues": {}}


def _get_cost_estimate():
    """Quick cost calculation."""
    try:
        from app.routers.metrics_advanced import _cost_accumulator, _cost_lock
        with _cost_lock:
            elapsed = time.time() - _cost_accumulator["session_start"]
            hours = max(elapsed / 3600, 0.001)
            base_cost = hours * 0.15
            cpu_cost = (_cost_accumulator["cpu_seconds"] / 3600) * 0.0416
            total = (base_cost + cpu_cost) / hours
            return round(total, 4)
    except Exception:
        return 0.0


def _get_hpa_replicas():
    """Get replica count."""
    try:
        return int(os.getenv("REPLICA_COUNT", "3"))
    except Exception:
        return 1


async def _sse_generator(request: Request):
    """Yields SSE frames every 1 second."""
    global _active_connections
    _active_connections += 1
    last_event_time = time.time()

    try:
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            # Collect all telemetry
            rps_stats = _compute_rps_stats()
            sys_metrics = _get_system_metrics()
            pool_stats = _get_pool_stats()
            queue_info = _get_queue_depth()
            cost = _get_cost_estimate()
            replicas = _get_hpa_replicas()
            events = get_recent_events(since=last_event_time)
            last_event_time = time.time()

            payload = {
                "timestamp": time.time(),
                # RPS & latency
                "rps": rps_stats["rps"],
                "error_rate": rps_stats["error_rate"],
                "p50": round(rps_stats["p50"], 1),
                "p95": round(rps_stats["p95"], 1),
                "p99": round(rps_stats["p99"], 1),
                "p999": round(rps_stats["p999"], 1),
                "total_requests": rps_stats["total"],
                # Throughput
                "throughput_in": _throughput_bytes["in"],
                "throughput_out": _throughput_bytes["out"],
                # System
                "cpu_percent": sys_metrics["cpu_percent"],
                "ram_percent": sys_metrics["ram_percent"],
                "ram_used_mb": sys_metrics["ram_used_mb"],
                "ram_total_mb": sys_metrics["ram_total_mb"],
                # CPU per pod (simulated for single pod)
                "cpu_per_pod": [sys_metrics["cpu_percent"]],
                "ram_per_pod": [sys_metrics["ram_percent"]],
                # DB Pool
                "pool_used": pool_stats["checked_out"],
                "pool_waiting": max(0, pool_stats["checked_out"] - pool_stats["pool_size"]),
                "pool_total": pool_stats["pool_size"],
                # Queue
                "queue_depth": queue_info["total"],
                "queue_breakdown": queue_info["queues"],
                # HPA
                "replicas": replicas,
                # Cost
                "cost_per_hour": cost,
                # Events
                "events": events,
                # Meta
                "active_connections": _active_connections,
            }

            # Format as SSE
            data = json.dumps(payload)
            yield f"data: {data}\n\n"

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        pass
    finally:
        _active_connections -= 1


@router.get("/stream")
async def sse_stream(request: Request):
    """
    Server-Sent Events stream. Pushes telemetry every 1 second.
    Connect via EventSource('/api/stream') in the browser.
    """
    return StreamingResponse(
        _sse_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/stream/status")
def stream_status():
    """Returns current SSE stream status."""
    return {
        "active_connections": _active_connections,
        "event_buffer_size": len(_event_buffer),
        "request_window_size": len(_request_window),
    }
