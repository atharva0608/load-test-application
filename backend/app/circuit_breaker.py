"""
StressForge Circuit Breaker — pybreaker integration for DB calls.
"""
from fastapi import APIRouter
import pybreaker
import logging
import time

logger = logging.getLogger("stressforge.circuit_breaker")

router = APIRouter(prefix="/api", tags=["Circuit Breaker"])


# ── Circuit Breaker instances ─────────────────────────

class StressForgeListener(pybreaker.CircuitBreakerListener):
    """Log circuit breaker state changes."""

    def state_change(self, cb, old_state, new_state):
        logger.warning(
            f"Circuit breaker '{cb.name}' state change: {old_state.name} → {new_state.name}"
        )

    def failure(self, cb, exc):
        logger.error(f"Circuit breaker '{cb.name}' recorded failure: {exc}")

    def success(self, cb):
        logger.debug(f"Circuit breaker '{cb.name}' recorded success")


# Database circuit breaker: opens if >50% error rate in 10s window
db_breaker = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=30,
    name="database",
    listeners=[StressForgeListener()],
)

# Redis circuit breaker
redis_breaker = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=15,
    name="redis",
    listeners=[StressForgeListener()],
)

# External API circuit breaker (for webhook/notification calls)
external_breaker = pybreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=60,
    name="external_api",
    listeners=[StressForgeListener()],
)

# Registry of all circuit breakers
BREAKERS = {
    "database": db_breaker,
    "redis": redis_breaker,
    "external_api": external_breaker,
}


def get_breaker_state(breaker: pybreaker.CircuitBreaker) -> dict:
    """Get the current state of a circuit breaker."""
    state = breaker.current_state
    return {
        "name": breaker.name,
        "state": state,
        "fail_count": breaker.fail_counter,
        "fail_max": breaker.fail_max,
        "reset_timeout": breaker.reset_timeout,
        "last_failure": None,  # pybreaker doesn't expose this directly
    }


@router.get("/circuit-breakers")
def get_circuit_breakers():
    """
    State of all circuit breakers: closed (healthy), open (rejecting), half-open (testing).
    """
    return {
        "breakers": [get_breaker_state(b) for b in BREAKERS.values()],
        "summary": {
            "total": len(BREAKERS),
            "closed": sum(1 for b in BREAKERS.values() if b.current_state == "closed"),
            "open": sum(1 for b in BREAKERS.values() if b.current_state == "open"),
            "half_open": sum(1 for b in BREAKERS.values() if b.current_state == "half-open"),
        },
    }


@router.post("/circuit-breakers/{name}/reset")
def reset_circuit_breaker(name: str):
    """Manually reset a circuit breaker to closed state."""
    breaker = BREAKERS.get(name)
    if not breaker:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Circuit breaker '{name}' not found")

    breaker.close()
    return {"status": "reset", "name": name, "new_state": breaker.current_state}


# ══════════════════════════════════════════════════════
# Chaos Injection Engine
# ══════════════════════════════════════════════════════

import threading
import collections

# Active chaos injections
_chaos_lock = threading.Lock()
_active_chaos: dict = {}  # {injection_id: {...}}
_chaos_log: collections.deque = collections.deque(maxlen=200)


def is_chaos_active(target: str) -> dict:
    """Check if chaos is active for a target (used by middleware/db calls)."""
    with _chaos_lock:
        for inj_id, inj in _active_chaos.items():
            if inj["target"] == target and time.time() < inj["expires_at"]:
                return inj
        return {}


def _expire_chaos():
    """Remove expired chaos injections."""
    now = time.time()
    with _chaos_lock:
        expired = [k for k, v in _active_chaos.items() if now >= v["expires_at"]]
        for k in expired:
            inj = _active_chaos.pop(k)
            inj["recovered_at"] = now
            inj["recovery_seconds"] = round(now - inj["injected_at"], 2)
            _chaos_log.append(inj)
            # Push SSE event
            try:
                from app.routers.stream import push_event
                push_event(
                    "chaos_recovery",
                    f"Chaos recovered: {inj['target']} {inj['failure_type']} "
                    f"after {inj['recovery_seconds']}s",
                    "success",
                )
            except Exception:
                pass


@router.post("/chaos/inject")
def inject_chaos(
    target: str = "redis",
    failure_type: str = "latency",
    latency_ms: int = 500,
    duration_seconds: int = 60,
):
    """
    Inject a chaos failure into the system.

    Targets: redis, database, network, application
    Failure types: latency, error, kill, memory_leak, pool_exhaust

    The injection auto-expires after duration_seconds.
    """
    _expire_chaos()  # Clean up expired first

    injection_id = f"{target}_{failure_type}_{int(time.time())}"
    injection = {
        "id": injection_id,
        "target": target,
        "failure_type": failure_type,
        "latency_ms": latency_ms,
        "duration_seconds": duration_seconds,
        "injected_at": time.time(),
        "expires_at": time.time() + duration_seconds,
        "status": "active",
    }

    with _chaos_lock:
        _active_chaos[injection_id] = injection

    # Push SSE event
    try:
        from app.routers.stream import push_event
        push_event(
            "chaos_injected",
            f"Chaos injected: {target} {failure_type} "
            f"({latency_ms}ms latency, {duration_seconds}s duration)",
            "error",
        )
    except Exception:
        pass

    # Execute immediate effects for certain types
    if target == "database" and failure_type == "error":
        # Force DB breaker open
        for _ in range(db_breaker.fail_max + 1):
            try:
                db_breaker.call(lambda: (_ for _ in ()).throw(Exception("Chaos: DB failure injected")))
            except Exception:
                pass

    elif target == "redis" and failure_type == "error":
        for _ in range(redis_breaker.fail_max + 1):
            try:
                redis_breaker.call(lambda: (_ for _ in ()).throw(Exception("Chaos: Redis failure injected")))
            except Exception:
                pass

    elif target == "application" and failure_type == "memory_leak":
        # Allocate memory that won't be freed until chaos expires
        import threading
        leak_mb = min(latency_ms // 10, 100)  # Reuse latency_ms field as MB

        def _leak():
            data = []
            for _ in range(leak_mb):
                chunk = bytearray(1024 * 1024)  # 1MB
                data.append(chunk)
            time.sleep(duration_seconds)

        threading.Thread(target=_leak, daemon=True).start()
        injection["leak_mb"] = leak_mb

    logger.warning(f"🔥 CHAOS INJECTED: {target}/{failure_type} for {duration_seconds}s")

    return {
        "status": "injected",
        "injection": injection,
        "active_count": len(_active_chaos),
    }


@router.get("/chaos/active")
def get_active_chaos():
    """Returns all currently active chaos injections."""
    _expire_chaos()
    with _chaos_lock:
        return {
            "active": list(_active_chaos.values()),
            "count": len(_active_chaos),
        }


@router.get("/chaos/log")
def get_chaos_log(limit: int = 50):
    """Returns history of chaos injections with recovery times."""
    _expire_chaos()
    with _chaos_lock:
        return {
            "log": list(_chaos_log)[-limit:],
            "total": len(_chaos_log),
        }


@router.delete("/chaos/clear")
def clear_all_chaos():
    """Immediately stops all active chaos injections."""
    with _chaos_lock:
        count = len(_active_chaos)
        for inj_id, inj in _active_chaos.items():
            inj["recovered_at"] = time.time()
            inj["recovery_seconds"] = round(time.time() - inj["injected_at"], 2)
            inj["status"] = "cleared"
            _chaos_log.append(inj)
        _active_chaos.clear()

    try:
        from app.routers.stream import push_event
        push_event("chaos_cleared", f"All {count} chaos injections cleared", "success")
    except Exception:
        pass

    # Reset all circuit breakers
    for b in BREAKERS.values():
        b.close()

    return {"status": "cleared", "cleared_count": count}

