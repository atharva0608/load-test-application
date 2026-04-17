"""
StressForge — Baseline / Regression Testing Router.
Capture golden baselines, compare against them, CI-compatible reports.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Dict, List, Optional
import time
import json
import threading

from app.routers.metrics_advanced import _latency_data, _latency_lock

router = APIRouter(prefix="/api/baseline", tags=["baseline"])

# ── In-memory baseline storage ──
_baseline_lock = threading.Lock()
_baseline: Optional[dict] = None  # { endpoint: { p50, p95, p99, count, captured_at } }


class BaselineEntry(BaseModel):
    endpoint: str
    p50: float
    p95: float
    p99: float
    count: int


class BaselineRecordResponse(BaseModel):
    status: str
    endpoints_captured: int
    captured_at: float
    baseline: Dict[str, dict]


class RegressionResult(BaseModel):
    endpoint: str
    baseline_p99: float
    current_p99: float
    delta_percent: float
    passed: bool
    threshold_percent: float


class CompareResponse(BaseModel):
    status: str  # "pass" | "fail"
    total_endpoints: int
    passed: int
    failed: int
    regressions: List[RegressionResult]
    captured_at: float
    compared_at: float


class ReportResponse(BaseModel):
    """CI-compatible report."""
    status: str
    pass_rate: float
    total_endpoints: int
    failures: List[dict]
    timestamp: float


# ── Endpoints ────────────────────────────────────────

@router.post("/record", response_model=BaselineRecordResponse)
def record_baseline():
    """
    Captures current latency percentiles as the golden baseline.
    Call this after a clean 5-minute warm-up run.
    """
    global _baseline
    baseline_data = {}

    with _latency_lock:
        for endpoint, values in _latency_data.items():
            if not values:
                continue
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            baseline_data[endpoint] = {
                "p50": sorted_vals[int(n * 0.50)],
                "p95": sorted_vals[int(n * 0.95)] if n > 1 else sorted_vals[-1],
                "p99": sorted_vals[int(n * 0.99)] if n > 2 else sorted_vals[-1],
                "count": n,
                "captured_at": time.time(),
            }

    with _baseline_lock:
        _baseline = {
            "data": baseline_data,
            "captured_at": time.time(),
        }

    return BaselineRecordResponse(
        status="baseline_captured",
        endpoints_captured=len(baseline_data),
        captured_at=_baseline["captured_at"],
        baseline=baseline_data,
    )


@router.post("/compare", response_model=CompareResponse)
def compare_against_baseline(threshold_percent: float = 20.0):
    """
    Compares current latency percentiles against the golden baseline.
    Fails if any endpoint's p99 regressed by more than threshold_percent%.
    """
    with _baseline_lock:
        if _baseline is None:
            return CompareResponse(
                status="no_baseline",
                total_endpoints=0,
                passed=0,
                failed=0,
                regressions=[],
                captured_at=0,
                compared_at=time.time(),
            )
        baseline_data = _baseline["data"]
        captured_at = _baseline["captured_at"]

    regressions = []
    with _latency_lock:
        for endpoint, values in _latency_data.items():
            if endpoint not in baseline_data or not values:
                continue
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            current_p99 = sorted_vals[int(n * 0.99)] if n > 2 else sorted_vals[-1]
            baseline_p99 = baseline_data[endpoint]["p99"]

            if baseline_p99 > 0:
                delta = ((current_p99 - baseline_p99) / baseline_p99) * 100
            else:
                delta = 0.0

            regressions.append(RegressionResult(
                endpoint=endpoint,
                baseline_p99=round(baseline_p99, 2),
                current_p99=round(current_p99, 2),
                delta_percent=round(delta, 2),
                passed=delta <= threshold_percent,
                threshold_percent=threshold_percent,
            ))

    passed = sum(1 for r in regressions if r.passed)
    failed = sum(1 for r in regressions if not r.passed)

    return CompareResponse(
        status="pass" if failed == 0 else "fail",
        total_endpoints=len(regressions),
        passed=passed,
        failed=failed,
        regressions=regressions,
        captured_at=captured_at,
        compared_at=time.time(),
    )


@router.get("/report", response_model=ReportResponse)
def baseline_report():
    """
    CI-compatible JSON report. Returns pass/fail for pipeline integration.
    """
    compare = compare_against_baseline()
    failures = [
        {
            "endpoint": r.endpoint,
            "baseline_p99": r.baseline_p99,
            "current_p99": r.current_p99,
            "regression_percent": r.delta_percent,
        }
        for r in compare.regressions if not r.passed
    ]

    total = compare.total_endpoints
    pass_rate = (compare.passed / total * 100) if total > 0 else 100.0

    return ReportResponse(
        status=compare.status,
        pass_rate=round(pass_rate, 2),
        total_endpoints=total,
        failures=failures,
        timestamp=time.time(),
    )
