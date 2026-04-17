"""
StressForge Queue Monitor Router — Queue depth, DLQ, job scheduling, burst fire.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from celery import Celery, chain, chord, group
import os
import redis
import json
import time
import logging

logger = logging.getLogger("stressforge.queue")

router = APIRouter(prefix="/api/queue", tags=["Queue Monitor"])

# Celery app — connects to the same broker as the worker
celery_app = Celery(
    "stressforge_queue",
    broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2"),
)

_redis_broker = None


def get_broker_redis():
    """Get a Redis connection to the Celery broker for queue inspection."""
    global _redis_broker
    if _redis_broker is None:
        broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
        _redis_broker = redis.Redis.from_url(broker_url, decode_responses=True)
    return _redis_broker


# ── Schemas ────────────────────────────────────────────
class QueueDepthResponse(BaseModel):
    pending: int = 0
    active: int = 0
    scheduled: int = 0
    failed: int = 0
    queues: dict = {}


class DLQItem(BaseModel):
    task_id: str
    task_name: str
    args: Optional[str] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None


class BurstRequest(BaseModel):
    count: int = Field(50, ge=1, le=1000, description="Number of tasks to fire")
    intensity: int = Field(30, ge=1, le=100, description="Task intensity")
    priority: str = Field("medium", description="Priority lane: high, medium, low")


class BurstResponse(BaseModel):
    tasks_queued: int
    queue: str
    duration_ms: float


class JobScheduleRequest(BaseModel):
    task_name: str = Field("heavy_computation", description="Task to schedule")
    delay_seconds: int = Field(30, ge=1, le=3600, description="Seconds from now")
    intensity: int = Field(50, ge=1, le=100)


class JobChainRequest(BaseModel):
    intensity: int = Field(30, ge=1, le=100)


class JobChordRequest(BaseModel):
    fan_out: int = Field(10, ge=2, le=50, description="Number of parallel tasks")
    intensity: int = Field(20, ge=1, le=100)


# ── Queue Depth ──────────────────────────────────────
@router.get("/depth", response_model=QueueDepthResponse)
def get_queue_depth():
    """
    Real-time queue depth across all Celery queues.
    Reads Redis LLEN for each known queue.
    """
    r = get_broker_redis()
    queues = ["celery", "default", "orders", "reports", "high_priority",
              "medium_priority", "low_priority", "celery_dead_letter"]

    queue_depths = {}
    total_pending = 0
    total_failed = 0

    for q in queues:
        try:
            depth = r.llen(q)
            queue_depths[q] = depth
            if q == "celery_dead_letter":
                total_failed = depth
            else:
                total_pending += depth
        except Exception:
            queue_depths[q] = 0

    # Try to get active task count via Celery inspect
    active_count = 0
    scheduled_count = 0
    try:
        inspector = celery_app.control.inspect(timeout=1.0)
        active = inspector.active()
        if active:
            for worker_tasks in active.values():
                active_count += len(worker_tasks)

        scheduled = inspector.scheduled()
        if scheduled:
            for worker_tasks in scheduled.values():
                scheduled_count += len(worker_tasks)
    except Exception as e:
        logger.warning(f"Celery inspect failed: {e}")

    return QueueDepthResponse(
        pending=total_pending,
        active=active_count,
        scheduled=scheduled_count,
        failed=total_failed,
        queues=queue_depths,
    )


# ── Dead Letter Queue ────────────────────────────────
@router.get("/dlq", response_model=List[DLQItem])
def get_dead_letter_queue():
    """
    List tasks in the dead letter queue (failed 3+ times).
    """
    r = get_broker_redis()
    dlq_items = []

    try:
        # Read up to 100 items from the DLQ
        raw_items = r.lrange("celery_dead_letter", 0, 99)
        for raw in raw_items:
            try:
                task_data = json.loads(raw)
                headers = task_data.get("headers", {})
                body = task_data.get("body", "")
                dlq_items.append(DLQItem(
                    task_id=headers.get("id", "unknown"),
                    task_name=headers.get("task", "unknown"),
                    args=str(body)[:200],
                    error=headers.get("errback", None),
                    timestamp=headers.get("eta", None),
                ))
            except (json.JSONDecodeError, KeyError):
                dlq_items.append(DLQItem(
                    task_id="unknown",
                    task_name="unparseable",
                    args=str(raw)[:200],
                ))
    except Exception as e:
        logger.error(f"DLQ read error: {e}")

    return dlq_items


@router.post("/dlq/retry/{task_id}")
def retry_dlq_task(task_id: str):
    """Retry a failed task from the DLQ by re-dispatching it."""
    r = get_broker_redis()

    try:
        raw_items = r.lrange("celery_dead_letter", 0, -1)
        for i, raw in enumerate(raw_items):
            try:
                task_data = json.loads(raw)
                headers = task_data.get("headers", {})
                if headers.get("id") == task_id:
                    task_name = headers.get("task", "worker.tasks.heavy_computation")
                    # Re-dispatch the task
                    celery_app.send_task(name=task_name, kwargs={"intensity": 30})
                    # Remove from DLQ
                    r.lrem("celery_dead_letter", 1, raw)
                    return {"status": "retried", "task_id": task_id, "task_name": task_name}
            except (json.JSONDecodeError, KeyError):
                continue

        raise HTTPException(status_code=404, detail=f"Task {task_id} not found in DLQ")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/dlq/{task_id}")
def discard_dlq_task(task_id: str):
    """Permanently discard a failed task from the DLQ."""
    r = get_broker_redis()

    try:
        raw_items = r.lrange("celery_dead_letter", 0, -1)
        for raw in raw_items:
            try:
                task_data = json.loads(raw)
                headers = task_data.get("headers", {})
                if headers.get("id") == task_id:
                    r.lrem("celery_dead_letter", 1, raw)
                    return {"status": "discarded", "task_id": task_id}
            except (json.JSONDecodeError, KeyError):
                continue

        raise HTTPException(status_code=404, detail=f"Task {task_id} not found in DLQ")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Burst Fire ────────────────────────────────────────
@router.post("/burst", response_model=BurstResponse)
def burst_fire(data: BurstRequest):
    """
    Fire N tasks instantly to saturate the queue.
    Tests queue depth buildup, worker throughput, and drain time.
    """
    start = time.time()

    priority_queue_map = {
        "high": "high_priority",
        "medium": "medium_priority",
        "low": "low_priority",
    }
    queue = priority_queue_map.get(data.priority, "default")

    for _ in range(data.count):
        celery_app.send_task(
            name="worker.tasks.priority_task",
            kwargs={"intensity": data.intensity, "priority": data.priority},
            queue=queue,
        )

    duration_ms = (time.time() - start) * 1000

    logger.info(f"Burst fired {data.count} tasks to queue '{queue}' in {duration_ms:.1f}ms")

    return BurstResponse(
        tasks_queued=data.count,
        queue=queue,
        duration_ms=round(duration_ms, 2),
    )


# ── Job Scheduling ────────────────────────────────────
jobs_router = APIRouter(prefix="/api/jobs", tags=["Job Scheduling"])


@jobs_router.post("/schedule")
def schedule_job(data: JobScheduleRequest):
    """Schedule a Celery task for future execution using ETA."""
    from datetime import datetime, timedelta, timezone

    eta = datetime.now(timezone.utc) + timedelta(seconds=data.delay_seconds)

    result = celery_app.send_task(
        name=f"worker.tasks.{data.task_name}",
        kwargs={"intensity": data.intensity},
        eta=eta,
    )

    return {
        "status": "scheduled",
        "task_id": result.id,
        "task_name": data.task_name,
        "eta": eta.isoformat(),
        "delay_seconds": data.delay_seconds,
    }


@jobs_router.post("/chain")
def fire_chain(data: JobChainRequest):
    """
    Fire a Celery chain: preprocess → compute → notify.
    Each step receives the result of the previous step.
    """
    start = time.time()

    workflow = chain(
        celery_app.signature(
            "worker.tasks.preprocess_data",
            kwargs={"intensity": data.intensity},
        ),
        celery_app.signature("worker.tasks.compute_result"),
        celery_app.signature("worker.tasks.send_notification"),
    )

    result = workflow.apply_async()
    duration_ms = (time.time() - start) * 1000

    return {
        "status": "dispatched",
        "chain_id": result.id,
        "steps": ["preprocess_data", "compute_result", "send_notification"],
        "dispatch_ms": round(duration_ms, 2),
    }


@jobs_router.post("/chord")
def fire_chord(data: JobChordRequest):
    """
    Fan out N parallel tasks → aggregate result.
    The hardest pattern to scale in Celery.
    """
    start = time.time()

    # Create N parallel tasks
    parallel_tasks = group(
        celery_app.signature(
            "worker.tasks.compute_result",
            kwargs={"input_data": {"shard": i, "intensity": data.intensity}},
        )
        for i in range(data.fan_out)
    )

    # Chord: run all in parallel, then aggregate
    workflow = chord(parallel_tasks)(
        celery_app.signature("worker.tasks.aggregate_results")
    )

    duration_ms = (time.time() - start) * 1000

    return {
        "status": "dispatched",
        "chord_id": workflow.id,
        "fan_out": data.fan_out,
        "dispatch_ms": round(duration_ms, 2),
    }
