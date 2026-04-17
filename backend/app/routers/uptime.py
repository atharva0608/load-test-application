"""
StressForge Uptime Router — SLA tracking, incidents, heartbeat history.
Reads data written by the uptime_heartbeat Celery beat task in Redis.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List
import redis
import json
import time
import os
import logging

logger = logging.getLogger("stressforge.uptime")

router = APIRouter(prefix="/api/uptime", tags=["Uptime Monitoring"])

_redis = None


def get_redis():
    global _redis
    if _redis is None:
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        _redis = redis.Redis.from_url(redis_url, decode_responses=True)
    return _redis


# ── Schemas ──────────────────────────────────────────

class SLASummary(BaseModel):
    period: str
    uptime_percent: float
    total_checks: int
    successful_checks: int
    failed_checks: int


class UptimeSummaryResponse(BaseModel):
    current_status: str  # "operational", "degraded", "down"
    sla: List[SLASummary]


class IncidentResponse(BaseModel):
    endpoint: str
    started_at: float
    resolved_at: Optional[float] = None
    duration_seconds: Optional[float] = None
    cause: Optional[str] = None
    status: str = "resolved"  # "active" or "resolved"


class HeartbeatEntry(BaseModel):
    endpoint: str
    status: str
    latency_ms: float
    error_reason: Optional[str] = None
    timestamp: float


class EndpointStatus(BaseModel):
    endpoint: str
    status: str
    latency_ms: float
    uptime_1h_percent: float
    avg_latency_1h_ms: float


# ── Endpoints ─────────────────────────────────────────

@router.get("/summary", response_model=UptimeSummaryResponse)
def get_uptime_summary():
    """
    SLA percentages for 1h / 24h / 7d / 30d.
    Computed from heartbeat history stored in Redis.
    """
    r = get_redis()

    # Determine current overall status
    current_status = "operational"
    try:
        latest_raw = r.get("stressforge:heartbeat:latest")
        if latest_raw:
            latest = json.loads(latest_raw)
            for entry in latest:
                if entry.get("status") == "down":
                    current_status = "down"
                    break
                elif entry.get("status") == "degraded":
                    current_status = "degraded"
    except Exception:
        current_status = "unknown"

    # Calculate SLA for different periods
    periods = {
        "1h": 360,       # 3600s / 10s interval = 360 checks
        "24h": 8640,     # 86400s / 10s = 8640 checks
        "7d": 60480,     # but we only keep 8640, so cap it
        "30d": 259200,   # same cap
    }

    sla_results = []
    endpoint = "/api/health/ready"
    history_key = f"stressforge:heartbeat:history:{endpoint}"

    for period_name, max_checks in periods.items():
        try:
            # Read heartbeat entries for the period
            actual_max = min(max_checks, 8640)
            entries_raw = r.lrange(history_key, 0, actual_max - 1)
            total = len(entries_raw)
            successful = 0

            for raw in entries_raw:
                try:
                    entry = json.loads(raw)
                    if entry.get("status") in ("healthy", "operational"):
                        successful += 1
                except (json.JSONDecodeError, KeyError):
                    pass

            if total > 0:
                uptime_pct = round((successful / total) * 100, 2)
            else:
                uptime_pct = 100.0  # No data = assume healthy

            sla_results.append(SLASummary(
                period=period_name,
                uptime_percent=uptime_pct,
                total_checks=total,
                successful_checks=successful,
                failed_checks=total - successful,
            ))
        except Exception as e:
            logger.error(f"SLA calc error for {period_name}: {e}")
            sla_results.append(SLASummary(
                period=period_name,
                uptime_percent=100.0,
                total_checks=0,
                successful_checks=0,
                failed_checks=0,
            ))

    return UptimeSummaryResponse(
        current_status=current_status,
        sla=sla_results,
    )


@router.get("/incidents", response_model=List[IncidentResponse])
def get_incidents():
    """
    List past incidents with duration and cause.
    Includes both active and resolved incidents.
    """
    r = get_redis()
    incidents = []

    # Active incidents
    try:
        for key in r.scan_iter("stressforge:incident:active:*"):
            raw = r.get(key)
            if raw:
                data = json.loads(raw)
                data["status"] = "active"
                data["duration_seconds"] = round(time.time() - data.get("started_at", time.time()), 2)
                incidents.append(IncidentResponse(**data))
    except Exception as e:
        logger.error(f"Active incidents read error: {e}")

    # Resolved incidents (last 100)
    try:
        resolved_raw = r.lrange("stressforge:incidents:resolved", 0, 99)
        for raw in resolved_raw:
            try:
                data = json.loads(raw)
                data["status"] = "resolved"
                incidents.append(IncidentResponse(**data))
            except (json.JSONDecodeError, KeyError):
                pass
    except Exception as e:
        logger.error(f"Resolved incidents read error: {e}")

    # Sort by started_at desc
    incidents.sort(key=lambda x: x.started_at, reverse=True)
    return incidents


@router.get("/history", response_model=List[HeartbeatEntry])
def get_heartbeat_history(endpoint: str = "/api/health/ready", limit: int = 360):
    """
    Raw heartbeat log with latency.
    Default: last 1 hour (360 entries @ 10s interval).
    """
    r = get_redis()
    history_key = f"stressforge:heartbeat:history:{endpoint}"

    entries = []
    try:
        raw_entries = r.lrange(history_key, 0, min(limit, 8640) - 1)
        for raw in raw_entries:
            try:
                data = json.loads(raw)
                entries.append(HeartbeatEntry(**data))
            except (json.JSONDecodeError, KeyError):
                pass
    except Exception as e:
        logger.error(f"History read error: {e}")

    return entries


@router.get("/endpoints", response_model=List[EndpointStatus])
def get_endpoint_status():
    """
    Per-endpoint health status with 1h SLA and average latency.
    """
    r = get_redis()
    endpoints = ["/api/health", "/api/health/ready"]
    statuses = []

    for endpoint in endpoints:
        history_key = f"stressforge:heartbeat:history:{endpoint}"
        status = "healthy"
        latency = 0.0
        uptime_pct = 100.0
        avg_latency = 0.0

        try:
            # Get latest
            latest_raw = r.get("stressforge:heartbeat:latest")
            if latest_raw:
                latest = json.loads(latest_raw)
                for entry in latest:
                    if entry.get("endpoint") == endpoint:
                        status = entry.get("status", "unknown")
                        latency = entry.get("latency_ms", 0)
                        break

            # 1h stats (360 entries)
            entries_raw = r.lrange(history_key, 0, 359)
            total = len(entries_raw)
            successful = 0
            latency_sum = 0.0

            for raw in entries_raw:
                try:
                    data = json.loads(raw)
                    if data.get("status") in ("healthy", "operational"):
                        successful += 1
                    latency_sum += data.get("latency_ms", 0)
                except (json.JSONDecodeError, KeyError):
                    pass

            if total > 0:
                uptime_pct = round((successful / total) * 100, 2)
                avg_latency = round(latency_sum / total, 2)

        except Exception as e:
            logger.error(f"Endpoint status error for {endpoint}: {e}")

        statuses.append(EndpointStatus(
            endpoint=endpoint,
            status=status,
            latency_ms=latency,
            uptime_1h_percent=uptime_pct,
            avg_latency_1h_ms=avg_latency,
        ))

    return statuses
