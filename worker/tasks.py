"""
StressForge Celery Worker — Background task definitions.
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
    task_routes={
        "worker.tasks.process_order": {"queue": "orders"},
        "worker.tasks.generate_report": {"queue": "reports"},
        "worker.tasks.cleanup_expired": {"queue": "default"},
        "worker.tasks.heavy_computation": {"queue": "default"},
    },
)


@celery_app.task(bind=True, name="worker.tasks.process_order")
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


@celery_app.task(bind=True, name="worker.tasks.generate_report")
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


@celery_app.task(name="worker.tasks.cleanup_expired")
def cleanup_expired():
    """
    Cleanup task — simulates periodic database maintenance.
    """
    logger.info("Running cleanup task...")
    time.sleep(random.uniform(2, 8))

    cleaned = random.randint(10, 500)
    logger.info(f"Cleaned up {cleaned} expired records")
    return {"cleaned_records": cleaned, "status": "completed"}


@celery_app.task(name="worker.tasks.heavy_computation")
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
