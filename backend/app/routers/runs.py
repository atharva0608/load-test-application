"""
StressForge Test Runs Router — Persist test scenarios, history, reporting.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import json
import io
import csv

from app.database import get_db
from app.models import TestRun

router = APIRouter(prefix="/api/runs", tags=["Test Runs"])


# ── Schemas ────────────────────────────────────────────

class TestRunCreate(BaseModel):
    scenario_name: str = Field(..., min_length=1, max_length=255)
    config: dict = Field(default_factory=dict)


class TestRunUpdate(BaseModel):
    summary: Optional[dict] = None
    status: Optional[str] = None


class TestRunResponse(BaseModel):
    id: int
    scenario_name: str
    status: str
    config_json: Optional[dict] = None
    summary_json: Optional[dict] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    class Config:
        from_attributes = True


# ── Endpoints ──────────────────────────────────────────

@router.post("", response_model=TestRunResponse, status_code=201)
def start_run(data: TestRunCreate, db: Session = Depends(get_db)):
    """Start a named test run — creates a record in Postgres."""
    run = TestRun(
        scenario_name=data.scenario_name,
        status="running",
        config_json=data.config,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    return _to_response(run)


@router.get("", response_model=List[TestRunResponse])
def list_runs(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List past test runs, newest first."""
    runs = (
        db.query(TestRun)
        .order_by(TestRun.started_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_to_response(r) for r in runs]


@router.get("/{run_id}", response_model=TestRunResponse)
def get_run(run_id: int, db: Session = Depends(get_db)):
    """Get full report for a specific test run."""
    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found")
    return _to_response(run)


@router.patch("/{run_id}", response_model=TestRunResponse)
def update_run(run_id: int, data: TestRunUpdate, db: Session = Depends(get_db)):
    """Update a running test — add summary data, mark as completed."""
    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found")

    if data.summary:
        run.summary_json = data.summary
    if data.status:
        run.status = data.status
        if data.status in ("completed", "failed", "cancelled"):
            from sqlalchemy.sql import func
            run.ended_at = func.now()

    db.commit()
    db.refresh(run)
    return _to_response(run)


@router.get("/{run_id}/export")
def export_run(run_id: int, format: str = "json", db: Session = Depends(get_db)):
    """Download test run data as JSON or CSV."""
    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found")

    run_data = _to_response(run).model_dump()

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)

        # Flatten the data
        writer.writerow(["field", "value"])
        for key, value in run_data.items():
            if isinstance(value, dict):
                for sub_key, sub_val in value.items():
                    writer.writerow([f"{key}.{sub_key}", str(sub_val)])
            else:
                writer.writerow([key, str(value)])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=run_{run_id}.csv"},
        )
    else:
        return StreamingResponse(
            iter([json.dumps(run_data, indent=2, default=str)]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=run_{run_id}.json"},
        )


@router.delete("/{run_id}")
def delete_run(run_id: int, db: Session = Depends(get_db)):
    """Delete a test run record."""
    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found")
    db.delete(run)
    db.commit()
    return {"status": "deleted", "run_id": run_id}


def _to_response(run: TestRun) -> TestRunResponse:
    """Convert ORM model to response, computing duration."""
    duration = None
    if run.started_at and run.ended_at:
        duration = round((run.ended_at - run.started_at).total_seconds(), 2)

    return TestRunResponse(
        id=run.id,
        scenario_name=run.scenario_name,
        status=run.status,
        config_json=run.config_json,
        summary_json=run.summary_json,
        started_at=run.started_at,
        ended_at=run.ended_at,
        duration_seconds=duration,
    )
