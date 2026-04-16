"""
StressForge Stress Router — CPU / Memory / IO / Mixed workload endpoints.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import StressRequest, StressResponse
import time
import hashlib
import random
import os
import tempfile
from celery import Celery

router = APIRouter(prefix="/api/stress", tags=["Stress Testing"])

# Connect to the Redis broker purely to dispatch messages
celery_app = Celery(
    "stressforge_api",
    broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1"),
)


def fibonacci(n: int) -> int:
    """Recursive fibonacci — intentionally inefficient for CPU stress."""
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def matrix_multiply(size: int):
    """Matrix multiplication — CPU-intensive."""
    a = [[random.random() for _ in range(size)] for _ in range(size)]
    b = [[random.random() for _ in range(size)] for _ in range(size)]
    result = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(size):
            for k in range(size):
                result[i][j] += a[i][k] * b[k][j]
    return len(result)


def bcrypt_rounds(n: int):
    """Hash N random strings with SHA-256 — CPU-intensive."""
    results = []
    for _ in range(n):
        data = os.urandom(64)
        for _ in range(100):
            data = hashlib.sha256(data).digest()
        results.append(data.hex()[:16])
    return results


@router.post("/cpu", response_model=StressResponse)
def stress_cpu(data: StressRequest):
    """
    CPU-intensive workload:
    - Fibonacci computation
    - Matrix multiplication
    - SHA-256 hash chains

    Intensity 1-100 scales the workload proportionally.
    """
    start = time.time()
    intensity = data.intensity

    # Fibonacci
    fib_n = 1000 * intensity
    fib_result = fibonacci(fib_n)

    # Matrix multiplication
    matrix_size = max(5, intensity // 2)
    matrix_multiply(matrix_size)

    # Hash chains
    hash_count = intensity * 10
    bcrypt_rounds(hash_count)

    duration_ms = (time.time() - start) * 1000

    return StressResponse(
        type="cpu",
        intensity=intensity,
        duration_ms=round(duration_ms, 2),
        result=f"fib({fib_n}) computed: {fib_result.bit_length()} bits long.",
        details={
            "fibonacci_n": fib_n,
            "matrix_size": f"{matrix_size}x{matrix_size}",
            "hash_chains": hash_count,
        },
    )


@router.post("/memory", response_model=StressResponse)
def stress_memory(data: StressRequest):
    """
    Memory-intensive workload:
    - Allocate large arrays
    - Hold in memory for specified duration

    Intensity scales memory allocation (1-100 MB).
    """
    start = time.time()
    intensity = data.intensity
    hold_seconds = min(data.duration_seconds or 2, 30)

    # Allocate memory (intensity MB)
    mb_to_allocate = intensity
    chunks = []
    for _ in range(mb_to_allocate):
        # Each chunk is ~1 MB
        chunk = bytearray(1024 * 1024)
        # Write random data to prevent optimization
        for i in range(0, len(chunk), 4096):
            chunk[i] = random.randint(0, 255)
        chunks.append(chunk)

    # Hold memory
    time.sleep(min(hold_seconds, 5))

    total_bytes = sum(len(c) for c in chunks)

    # Release
    del chunks

    duration_ms = (time.time() - start) * 1000

    return StressResponse(
        type="memory",
        intensity=intensity,
        duration_ms=round(duration_ms, 2),
        result=f"Allocated {mb_to_allocate} MB, held for {hold_seconds}s",
        details={
            "allocated_mb": mb_to_allocate,
            "total_bytes": total_bytes,
            "hold_seconds": hold_seconds,
        },
    )


@router.post("/io", response_model=StressResponse)
def stress_io(data: StressRequest, db: Session = Depends(get_db)):
    """
    I/O-intensive workload:
    - Heavy database queries
    - Temporary file writes
    - Multiple sequential reads

    Intensity scales the number of operations.
    """
    start = time.time()
    intensity = data.intensity

    # DB queries
    db_queries = intensity * 5
    for i in range(db_queries):
        res = db.execute(
            __import__("sqlalchemy").text(
                "SELECT id FROM products LIMIT 10"
            )
        )
        res.fetchall()

    # File I/O
    file_ops = intensity * 2
    temp_files = []
    for i in range(file_ops):
        fd, path = tempfile.mkstemp(prefix="stressforge_")
        data_bytes = os.urandom(1024 * 10)  # 10 KB per file
        os.write(fd, data_bytes)
        os.close(fd)
        temp_files.append(path)

    # Read back
    for path in temp_files:
        with open(path, "rb") as f:
            _ = f.read()

    # Cleanup
    for path in temp_files:
        try:
            os.unlink(path)
        except OSError:
            pass

    duration_ms = (time.time() - start) * 1000

    return StressResponse(
        type="io",
        intensity=intensity,
        duration_ms=round(duration_ms, 2),
        result=f"{db_queries} DB queries, {file_ops} file ops",
        details={
            "db_queries": db_queries,
            "file_writes": file_ops,
            "file_reads": file_ops,
            "total_file_bytes": file_ops * 10240,
        },
    )


@router.post("/mixed", response_model=StressResponse)
def stress_mixed(data: StressRequest, db: Session = Depends(get_db)):
    """
    Mixed workload — combines CPU, Memory, and I/O.
    Simulates real-world application load.
    """
    start = time.time()
    intensity = data.intensity

    # CPU: Fibonacci + hashing
    fib_result = fibonacci(500 * intensity)
    hash_count = intensity * 5
    bcrypt_rounds(hash_count)

    # Memory: Allocate and process
    mb = max(1, intensity // 10)
    chunks = [bytearray(1024 * 1024) for _ in range(mb)]
    for chunk in chunks:
        for i in range(0, len(chunk), 8192):
            chunk[i] = random.randint(0, 255)

    # I/O: DB queries
    db_queries = intensity * 2
    for _ in range(db_queries):
        res = db.execute(
            __import__("sqlalchemy").text(
                "SELECT COUNT(*) FROM products WHERE price > :price"
            ),
            {"price": random.uniform(10, 500)},
        )
        res.fetchall()

    # Cleanup
    del chunks

    duration_ms = (time.time() - start) * 1000

    return StressResponse(
        type="mixed",
        intensity=intensity,
        duration_ms=round(duration_ms, 2),
        result=f"CPU+Memory+IO combined at intensity {intensity} | Fib: {fib_result.bit_length()} bits",
        details={
            "fibonacci_n": 500 * intensity,
            "hash_chains": hash_count,
            "memory_mb": mb,
            "db_queries": db_queries,
        },
    )

@router.post("/celery", response_model=StressResponse)
def stress_celery(data: StressRequest):
    """
    Celery Worker workload:
    - Dispatches async jobs to the Redis broker.
    - Simulates heavy background worker queue pressure.
    """
    start = time.time()
    intensity = data.intensity
    
    tasks_to_spawn = intensity * 2
    task_ids = []
    
    for _ in range(tasks_to_spawn):
        # Fire-and-forget task dispatch
        result = celery_app.send_task(
            name="worker.tasks.heavy_computation",
            kwargs={"intensity": intensity}
        )
        task_ids.append(result.id)

    duration_ms = (time.time() - start) * 1000

    return StressResponse(
        type="celery",
        intensity=intensity,
        duration_ms=round(duration_ms, 2),
        result=f"Queued {tasks_to_spawn} heavy_computation tasks successfully",
        details={
            "tasks_spawned": tasks_to_spawn,
            "broker": celery_app.conf.broker_url
        },
    )

