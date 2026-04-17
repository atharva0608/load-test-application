"""
StressForge Celery Worker — Background task definitions.
Includes priority lanes, DLQ routing, chain/chord tasks.
"""
from celery import Celery
import time
import random
import hashlib
import os
import logging

logger = logging.getLogger(__name__)

# Celery app
celery_app = Celery(
    "stressforge_worker",
    broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2"),
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_concurrency=8,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Priority queue routing
    task_routes={
        "worker.tasks.process_order": {"queue": "orders"},
        "worker.tasks.generate_report": {"queue": "reports"},
        "worker.tasks.cleanup_expired": {"queue": "default"},
        "worker.tasks.heavy_computation": {"queue": "default"},
        "worker.tasks.priority_task": None,  # Routed dynamically by caller
        "worker.tasks.preprocess_data": {"queue": "default"},
        "worker.tasks.compute_result": {"queue": "default"},
        "worker.tasks.send_notification": {"queue": "default"},
        "worker.tasks.aggregate_results": {"queue": "default"},
        "worker.tasks.uptime_heartbeat": {"queue": "default"},
    },
    # Dead Letter Queue — tasks failing max_retries go to DLQ
    task_default_queue="default",
    task_queues={
        "default": {},
        "orders": {},
        "reports": {},
        "high_priority": {},
        "medium_priority": {},
        "low_priority": {},
        "celery_dead_letter": {},
    },
    # Celery Beat schedule — periodic tasks
    beat_schedule={
        "uptime-heartbeat-every-10s": {
            "task": "worker.tasks.uptime_heartbeat",
            "schedule": 10.0,  # Every 10 seconds
        },
    },
)


def send_to_dlq(task, exc, task_id, args, kwargs, einfo):
    """Error callback: send permanently failed tasks to DLQ."""
    import redis
    import json
    try:
        broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
        r = redis.Redis.from_url(broker_url, decode_responses=True)
        dlq_entry = json.dumps({
            "headers": {
                "id": task_id,
                "task": task.name,
                "errback": str(exc),
            },
            "body": str(kwargs)[:500],
            "timestamp": time.time(),
        })
        r.rpush("celery_dead_letter", dlq_entry)
        logger.error(f"Task {task_id} ({task.name}) sent to DLQ after {task.max_retries} retries: {exc}")
    except Exception as e:
        logger.error(f"Failed to send task to DLQ: {e}")


# ── Original Tasks ───────────────────────────────────

@celery_app.task(bind=True, name="worker.tasks.process_order",
                 max_retries=3, on_failure=send_to_dlq)
def process_order(self, order_id: int, user_id: int):
    """
    Simulate order fulfillment processing.
    Takes 5-30 seconds depending on order complexity.
    """
    logger.info(f"Processing order #{order_id} for user #{user_id}")
    self.update_state(state="PROCESSING", meta={"order_id": order_id, "step": "validating"})

    # Simulate validation
    time.sleep(random.uniform(1, 3))
    self.update_state(state="PROCESSING", meta={"order_id": order_id, "step": "charging"})

    # Simulate payment processing
    time.sleep(random.uniform(2, 5))
    self.update_state(state="PROCESSING", meta={"order_id": order_id, "step": "fulfilling"})

    # Simulate fulfillment
    time.sleep(random.uniform(2, 10))
    self.update_state(state="PROCESSING", meta={"order_id": order_id, "step": "shipping"})

    # Simulate shipping
    time.sleep(random.uniform(1, 5))

    logger.info(f"Order #{order_id} processed successfully")
    return {
        "order_id": order_id,
        "status": "completed",
        "tracking_number": f"SF-{random.randint(100000, 999999)}",
    }


@celery_app.task(bind=True, name="worker.tasks.generate_report",
                 max_retries=3, on_failure=send_to_dlq)
def generate_report(self, report_type: str = "daily"):
    """
    Generate a CPU-intensive report.
    Simulates aggregation of large datasets.
    """
    logger.info(f"Generating {report_type} report...")
    self.update_state(state="PROCESSING", meta={"report_type": report_type, "progress": 0})

    # Simulate heavy computation
    data = []
    total_steps = 100
    for step in range(total_steps):
        # CPU work: hash chains
        value = os.urandom(256)
        for _ in range(500):
            value = hashlib.sha256(value).digest()
        data.append(value.hex()[:32])

        if step % 10 == 0:
            self.update_state(
                state="PROCESSING",
                meta={"report_type": report_type, "progress": int((step / total_steps) * 100)},
            )

    logger.info(f"{report_type} report generated ({len(data)} entries)")
    return {
        "report_type": report_type,
        "entries": len(data),
        "status": "completed",
    }


@celery_app.task(name="worker.tasks.cleanup_expired",
                 max_retries=3, on_failure=send_to_dlq)
def cleanup_expired():
    """
    Cleanup task — simulates periodic database maintenance.
    """
    logger.info("Running cleanup task...")
    time.sleep(random.uniform(2, 8))

    cleaned = random.randint(10, 500)
    logger.info(f"Cleaned up {cleaned} expired records")
    return {"cleaned_records": cleaned, "status": "completed"}


@celery_app.task(name="worker.tasks.heavy_computation",
                 max_retries=3, on_failure=send_to_dlq)
def heavy_computation(intensity: int = 50):
    """
    Generic heavy computation task for stress testing.
    """
    logger.info(f"Starting heavy computation (intensity={intensity})")
    start = time.time()

    # Matrix-like computation
    size = intensity * 10
    data = [random.random() for _ in range(size * size)]

    result = 0.0
    for i in range(len(data)):
        result += data[i] * (i % 17 + 1)
        if i % 1000 == 0:
            result = hashlib.md5(str(result).encode()).hexdigest()
            result = float(int(result[:8], 16))

    duration = time.time() - start
    logger.info(f"Heavy computation done in {duration:.2f}s")
    return {
        "intensity": intensity,
        "duration_seconds": round(duration, 3),
        "result_hash": hashlib.sha256(str(result).encode()).hexdigest()[:16],
    }


# ── Priority Task (with DLQ support) ─────────────────

@celery_app.task(bind=True, name="worker.tasks.priority_task",
                 max_retries=3, on_failure=send_to_dlq)
def priority_task(self, intensity: int = 30, priority: str = "medium"):
    """
    Priority-aware task for burstable job pool testing.
    HIGH: fast processing, simulates order processing
    MEDIUM: moderate work, simulates standard API work
    LOW: heavy computation, simulates report generation
    """
    logger.info(f"Priority task [{priority.upper()}] starting (intensity={intensity})")
    start = time.time()

    if priority == "high":
        # Fast — simulate critical path (payment, order)
        time.sleep(random.uniform(0.1, 0.5))
        value = os.urandom(64)
        for _ in range(intensity * 10):
            value = hashlib.sha256(value).digest()
        result_type = "critical_path"

    elif priority == "low":
        # Heavy — simulate report/analytics generation
        time.sleep(random.uniform(1, 3))
        data = [random.random() for _ in range(intensity * 50)]
        total = sum(x * (i % 7 + 1) for i, x in enumerate(data))
        value = hashlib.sha256(str(total).encode()).digest()
        result_type = "analytics"

    else:
        # Medium — standard workload
        time.sleep(random.uniform(0.3, 1.5))
        value = os.urandom(128)
        for _ in range(intensity * 30):
            value = hashlib.sha256(value).digest()
        result_type = "standard"

    duration = time.time() - start
    logger.info(f"Priority task [{priority.upper()}] done in {duration:.2f}s")

    return {
        "priority": priority,
        "intensity": intensity,
        "type": result_type,
        "duration_seconds": round(duration, 3),
        "result_hash": hashlib.sha256(value).hexdigest()[:16] if isinstance(value, bytes) else str(value)[:16],
    }


# ── Chain Tasks (preprocess → compute → notify) ──────

@celery_app.task(bind=True, name="worker.tasks.preprocess_data",
                 max_retries=3, on_failure=send_to_dlq)
def preprocess_data(self, intensity: int = 30, **kwargs):
    """
    Step 1 of chain: Data preprocessing.
    Simulates ETL-style data cleaning and transformation.
    """
    logger.info(f"[Chain Step 1] Preprocessing data (intensity={intensity})")
    start = time.time()

    # Simulate data cleaning
    records = intensity * 100
    cleaned_data = []
    for i in range(records):
        raw = os.urandom(32)
        cleaned = hashlib.md5(raw).hexdigest()
        cleaned_data.append(cleaned)

    time.sleep(random.uniform(0.5, 2))
    duration = time.time() - start

    logger.info(f"[Chain Step 1] Preprocessed {records} records in {duration:.2f}s")
    return {
        "step": "preprocess",
        "records_processed": records,
        "duration_seconds": round(duration, 3),
        "output_hash": hashlib.sha256(str(cleaned_data[:10]).encode()).hexdigest()[:16],
    }


@celery_app.task(bind=True, name="worker.tasks.compute_result",
                 max_retries=3, on_failure=send_to_dlq)
def compute_result(self, input_data=None, **kwargs):
    """
    Step 2 of chain (or parallel shard in chord): Heavy computation.
    Receives output from preprocess_data or acts as an independent shard.
    """
    shard_id = None
    intensity = 30

    if isinstance(input_data, dict):
        shard_id = input_data.get("shard")
        intensity = input_data.get("intensity", 30)

    logger.info(f"[Chain Step 2 / Shard {shard_id}] Computing result (intensity={intensity})")
    start = time.time()

    # CPU-intensive computation
    result = 0.0
    iterations = intensity * 500
    for i in range(iterations):
        result += (i * 17 + 3) ** 0.5
        if i % 200 == 0:
            result = float(int(hashlib.md5(str(result).encode()).hexdigest()[:8], 16))

    time.sleep(random.uniform(0.3, 1.5))
    duration = time.time() - start

    logger.info(f"[Chain Step 2 / Shard {shard_id}] Computed in {duration:.2f}s")
    return {
        "step": "compute",
        "shard_id": shard_id,
        "iterations": iterations,
        "duration_seconds": round(duration, 3),
        "result_value": round(result, 4),
    }


@celery_app.task(bind=True, name="worker.tasks.send_notification",
                 max_retries=3, on_failure=send_to_dlq)
def send_notification(self, input_data=None, **kwargs):
    """
    Step 3 of chain: Send notification (simulated).
    Receives output from compute_result.
    """
    logger.info("[Chain Step 3] Sending notification...")
    start = time.time()

    # Simulate notification delivery (email, webhook, etc.)
    time.sleep(random.uniform(0.2, 0.8))

    duration = time.time() - start
    logger.info(f"[Chain Step 3] Notification sent in {duration:.2f}s")

    return {
        "step": "notify",
        "channel": "email",
        "recipient": "admin@stressforge.io",
        "duration_seconds": round(duration, 3),
        "status": "delivered",
        "previous_step_data": str(input_data)[:200] if input_data else None,
    }


# ── Chord Aggregator ─────────────────────────────────

@celery_app.task(name="worker.tasks.aggregate_results",
                 max_retries=3, on_failure=send_to_dlq)
def aggregate_results(results):
    """
    Chord callback: aggregates results from N parallel compute shards.
    """
    logger.info(f"[Chord Aggregator] Aggregating {len(results)} shard results")
    start = time.time()

    total_iterations = 0
    total_duration = 0.0
    shard_values = []

    for r in results:
        if isinstance(r, dict):
            total_iterations += r.get("iterations", 0)
            total_duration += r.get("duration_seconds", 0)
            shard_values.append(r.get("result_value", 0))

    # Simulate aggregation work
    time.sleep(random.uniform(0.3, 1.0))
    agg_duration = time.time() - start

    logger.info(f"[Chord Aggregator] Aggregated in {agg_duration:.2f}s")
    return {
        "step": "aggregate",
        "shards_aggregated": len(results),
        "total_iterations": total_iterations,
        "total_compute_seconds": round(total_duration, 3),
        "aggregate_value": round(sum(shard_values), 4),
        "aggregation_seconds": round(agg_duration, 3),
    }


# ── Uptime Heartbeat Task ────────────────────────────

@celery_app.task(name="worker.tasks.uptime_heartbeat")
def uptime_heartbeat():
    """
    Periodic heartbeat task for uptime monitoring.
    Pings the API health endpoint and records results.
    """
    import urllib.request
    import json as json_mod

    api_base = os.getenv("API_INTERNAL_URL", "http://api:8000")
    endpoints = [
        "/api/health",
        "/api/health/ready",
    ]

    results = []
    for endpoint in endpoints:
        start = time.time()
        status = "healthy"
        error_reason = None
        latency_ms = 0

        try:
            url = f"{api_base}{endpoint}"
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", "StressForge-Heartbeat/1.0")
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
                latency_ms = round((time.time() - start) * 1000, 2)
                if resp.status != 200:
                    status = "degraded"
        except Exception as e:
            latency_ms = round((time.time() - start) * 1000, 2)
            status = "down"
            error_reason = str(e)[:200]

        results.append({
            "endpoint": endpoint,
            "status": status,
            "latency_ms": latency_ms,
            "error_reason": error_reason,
            "timestamp": time.time(),
        })

    # Store in Redis for quick access (the uptime router reads this)
    try:
        import redis as redis_mod
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        r = redis_mod.Redis.from_url(redis_url, decode_responses=True)

        # Store latest heartbeat results
        r.set("stressforge:heartbeat:latest", json_mod.dumps(results), ex=60)

        # Append to heartbeat history (keep last 8640 = 24h @ 10s intervals)
        for res in results:
            history_key = f"stressforge:heartbeat:history:{res['endpoint']}"
            r.lpush(history_key, json_mod.dumps(res))
            r.ltrim(history_key, 0, 8639)

        # Track consecutive failures for incident detection
        for res in results:
            fail_key = f"stressforge:heartbeat:consecutive_fails:{res['endpoint']}"
            if res["status"] == "down":
                r.incr(fail_key)
                fails = int(r.get(fail_key) or 0)
                if fails >= 3:
                    # Create incident
                    incident_key = f"stressforge:incident:active:{res['endpoint']}"
                    if not r.exists(incident_key):
                        incident = {
                            "endpoint": res["endpoint"],
                            "started_at": time.time(),
                            "cause": res["error_reason"],
                            "consecutive_failures": fails,
                        }
                        r.set(incident_key, json_mod.dumps(incident))
                        logger.warning(f"INCIDENT DETECTED: {res['endpoint']} down for {fails} consecutive checks")
            else:
                # Check if recovering from incident
                incident_key = f"stressforge:incident:active:{res['endpoint']}"
                if r.exists(incident_key):
                    incident_data = json_mod.loads(r.get(incident_key))
                    incident_data["resolved_at"] = time.time()
                    incident_data["duration_seconds"] = round(
                        incident_data["resolved_at"] - incident_data["started_at"], 2
                    )
                    # Move to resolved incidents list
                    r.lpush("stressforge:incidents:resolved", json_mod.dumps(incident_data))
                    r.ltrim("stressforge:incidents:resolved", 0, 499)
                    r.delete(incident_key)
                    logger.info(f"INCIDENT RESOLVED: {res['endpoint']} recovered after {incident_data['duration_seconds']}s")
                r.set(fail_key, 0)

    except Exception as e:
        logger.error(f"Heartbeat Redis write failed: {e}")

    return results
