from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime

from core.db import get_db
from core.models import AnalysisRun, Issue, RunStatus, RunSource
from core.schemas import AnalysisRunResponse, AnalysisRunCreate

router = APIRouter()


@router.get("/runs/latest", response_model=AnalysisRunResponse)
async def get_latest_run(db: Session = Depends(get_db)):
    """Get the most recent analysis run"""
    
    run = db.query(AnalysisRun).order_by(desc(AnalysisRun.created_at)).first()
    
    if not run:
        raise HTTPException(status_code=404, detail="No analysis runs found")
    
    return AnalysisRunResponse.from_orm(run)


@router.get("/runs/{run_id}", response_model=AnalysisRunResponse)
async def get_run(run_id: int, db: Session = Depends(get_db)):
    """Get a specific analysis run"""
    
    run = db.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
    
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    
    return AnalysisRunResponse.from_orm(run)


@router.get("/runs", response_model=List[AnalysisRunResponse])
async def list_runs(
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """List recent analysis runs"""
    
    runs = db.query(AnalysisRun).order_by(
        desc(AnalysisRun.created_at)
    ).limit(limit).all()
    
    return [AnalysisRunResponse.from_orm(run) for run in runs]


@router.get("/runs/{run_id}/stats")
async def get_run_stats(run_id: int, db: Session = Depends(get_db)):
    """Get statistics for a specific run"""
    
    run = db.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
    
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    
    # Get issue counts by severity
    severity_counts = db.query(
        Issue.severity,
        func.count(Issue.id).label('count')
    ).filter(Issue.first_seen_run_id == run_id).group_by(Issue.severity).all()
    
    # Get issue counts by rule
    rule_counts = db.query(
        Issue.rule_code,
        func.count(Issue.id).label('count')
    ).filter(Issue.first_seen_run_id == run_id).group_by(Issue.rule_code).all()
    
    # Get issue counts by provenance
    provenance_counts = {}
    issues = db.query(Issue.provenance).filter(Issue.first_seen_run_id == run_id).all()
    for issue in issues:
        provenance = issue.provenance
        if "rule" in provenance and "llm" in provenance:
            key = "both"
        elif "rule" in provenance:
            key = "rule"
        elif "llm" in provenance:
            key = "llm"
        else:
            key = "unknown"
        
        provenance_counts[key] = provenance_counts.get(key, 0) + 1
    
    # Count auto-applicable issues
    auto_apply_count = db.query(Issue).filter(
        Issue.first_seen_run_id == run_id,
        Issue.can_auto_apply == True
    ).count()
    
    return {
        "run_id": run_id,
        "commit_sha": run.commit_sha,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_seconds": (
            (run.finished_at - run.started_at).total_seconds() 
            if run.finished_at and run.started_at else None
        ),
        "llm_usage": {
            "tokens_in": run.llm_token_in,
            "tokens_out": run.llm_token_out,
            "cost_estimate": float(run.llm_cost_estimate) if run.llm_cost_estimate else 0.0
        },
        "issues": {
            "total": sum(count for _, count in severity_counts),
            "by_severity": {severity: count for severity, count in severity_counts},
            "by_rule": {rule: count for rule, count in rule_counts},
            "by_provenance": provenance_counts,
            "auto_applicable": auto_apply_count
        }
    }


@router.post("/runs", response_model=Dict[str, Any])
async def trigger_run(
    background_tasks: BackgroundTasks,
    source: str = "manual",
    db: Session = Depends(get_db)
):
    """Trigger a new analysis run"""
    
    # Check if there's already a running analysis
    existing_run = db.query(AnalysisRun).filter(
        AnalysisRun.status == RunStatus.RUNNING
    ).first()
    
    if existing_run:
        raise HTTPException(
            status_code=409,
            detail=f"Analysis run {existing_run.id} is already running"
        )
    
    # Create new run record
    new_run = AnalysisRun(
        commit_sha="",  # Will be filled by the actual runner
        source=RunSource(source),
        status=RunStatus.RUNNING,
        started_at=datetime.now()
    )
    
    db.add(new_run)
    db.commit()
    db.refresh(new_run)
    
    # Queue the background task
    background_tasks.add_task(run_analysis_task, new_run.id)
    
    return {
        "run_id": new_run.id,
        "status": "queued",
        "message": "Analysis run has been queued"
    }


async def run_analysis_task(run_id: int):
    """Background task to run the analysis"""
    # TODO: Import and call the actual crawler
    # from crawler.run_analysis import run_full_analysis
    # await run_full_analysis(run_id)
    
    # For now, just mark as completed
    from core.db import db
    with db.get_session() as session:
        run = session.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
        if run:
            run.status = RunStatus.SUCCESS
            run.finished_at = datetime.now()
            session.commit()


@router.delete("/runs/{run_id}")
async def cancel_run(run_id: int, db: Session = Depends(get_db)):
    """Cancel a running analysis"""
    
    run = db.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
    
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    
    if run.status != RunStatus.RUNNING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel run with status: {run.status}"
        )
    
    # TODO: Implement actual cancellation logic
    run.status = RunStatus.FAILED
    run.finished_at = datetime.now()
    
    db.commit()
    
    return {"message": f"Analysis run {run_id} cancelled"}