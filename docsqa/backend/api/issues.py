from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from core.db import get_db
from core.models import Issue, File, AnalysisRun
from core.schemas import (
    IssueResponse, IssueDetail, IssueUpdate, IssueFilters, 
    PaginatedResponse, BulkIssueUpdate, IssueState
)

router = APIRouter()


@router.get("/issues", response_model=PaginatedResponse)
async def list_issues(
    state: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    rule: Optional[str] = Query(None),
    file: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    provenance: Optional[str] = Query(None),
    has_patch: Optional[bool] = Query(None),
    can_auto_apply: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    sort: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """List issues with filtering and pagination"""
    
    # Build query
    query = db.query(Issue).join(File)
    
    # Apply filters
    if state:
        query = query.filter(Issue.state == state)
    
    if severity:
        query = query.filter(Issue.severity == severity)
    
    if rule:
        query = query.filter(Issue.rule_code.ilike(f"%{rule}%"))
    
    if file:
        query = query.filter(File.path.ilike(f"%{file}%"))
    
    if q:
        search_filter = or_(
            Issue.title.ilike(f"%{q}%"),
            Issue.description.ilike(f"%{q}%"),
            File.path.ilike(f"%{q}%")
        )
        query = query.filter(search_filter)
    
    if provenance:
        if provenance == "rule":
            query = query.filter(Issue.provenance.contains(["rule"]))
        elif provenance == "llm":
            query = query.filter(Issue.provenance.contains(["llm"]))
        elif provenance == "both":
            query = query.filter(and_(
                Issue.provenance.contains(["rule"]),
                Issue.provenance.contains(["llm"])
            ))
    
    if has_patch is not None:
        if has_patch:
            query = query.filter(Issue.suggested_patch.isnot(None))
        else:
            query = query.filter(Issue.suggested_patch.is_(None))
    
    if can_auto_apply is not None:
        query = query.filter(Issue.can_auto_apply == can_auto_apply)
    
    # Apply sorting
    if sort:
        if sort == "created_desc":
            query = query.order_by(Issue.created_at.desc())
        elif sort == "severity":
            # Custom severity ordering
            severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
            query = query.order_by(
                Issue.severity.case(severity_order).desc(),
                Issue.created_at.desc()
            )
        elif sort == "file":
            query = query.order_by(File.path, Issue.line_start)
    else:
        query = query.order_by(Issue.created_at.desc())
    
    # Get total count
    total = query.count()
    
    # Apply pagination
    offset = (page - 1) * limit
    issues = query.offset(offset).limit(limit).all()
    
    # Convert to response format
    issue_responses = []
    for issue in issues:
        response = IssueResponse.from_orm(issue)
        response.file_path = issue.file.path
        response.file_title = issue.file.title
        issue_responses.append(response)
    
    pages = (total + limit - 1) // limit
    
    return PaginatedResponse(
        items=issue_responses,
        total=total,
        page=page,
        limit=limit,
        pages=pages
    )


@router.get("/issues/{issue_id}", response_model=IssueDetail)
async def get_issue(issue_id: int, db: Session = Depends(get_db)):
    """Get detailed information about a specific issue"""
    
    issue = db.query(Issue).join(File).filter(Issue.id == issue_id).first()
    
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    
    # Build detailed response
    response = IssueDetail.from_orm(issue)
    response.file_path = issue.file.path
    response.file_title = issue.file.title
    
    # Add file content context if available
    try:
        # Get file content (simplified - in real system would get from git)
        with open(issue.file.path, 'r') as f:
            content = f.read()
            lines = content.split('\n')
            
            # Get context around the issue
            start = max(0, issue.line_start - 5)
            end = min(len(lines), issue.line_end + 5)
            context_lines = lines[start:end]
            
            response.rendered_context = '\n'.join(
                f"{i+start+1:4}: {line}" for i, line in enumerate(context_lines)
            )
    except Exception:
        response.rendered_context = "Could not load file content"
    
    return response


@router.patch("/issues/{issue_id}", response_model=IssueResponse)
async def update_issue(
    issue_id: int, 
    update_data: IssueUpdate, 
    db: Session = Depends(get_db)
):
    """Update an issue's state or metadata"""
    
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    
    # Apply updates
    update_dict = update_data.dict(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(issue, field, value)
    
    db.commit()
    db.refresh(issue)
    
    response = IssueResponse.from_orm(issue)
    response.file_path = issue.file.path
    response.file_title = issue.file.title
    
    return response


@router.post("/issues/bulk")
async def bulk_update_issues(
    bulk_update: BulkIssueUpdate,
    db: Session = Depends(get_db)
):
    """Bulk update issues matching filter criteria"""
    
    # Build query from filter
    query = db.query(Issue)
    
    filter_dict = bulk_update.filter
    if "state" in filter_dict:
        query = query.filter(Issue.state == filter_dict["state"])
    if "severity" in filter_dict:
        query = query.filter(Issue.severity == filter_dict["severity"])
    if "rule_code" in filter_dict:
        query = query.filter(Issue.rule_code == filter_dict["rule_code"])
    
    # Apply update
    update_count = query.update({"state": bulk_update.state})
    
    db.commit()
    
    return {
        "updated_count": update_count,
        "new_state": bulk_update.state
    }


@router.post("/issues/{issue_id}/stage")
async def stage_issue(issue_id: int, db: Session = Depends(get_db)):
    """Stage an issue for PR creation (add to working tree without commit)"""
    
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    
    if not issue.can_auto_apply:
        raise HTTPException(
            status_code=400, 
            detail="Issue cannot be auto-applied"
        )
    
    if not issue.suggested_patch:
        raise HTTPException(
            status_code=400,
            detail="Issue has no suggested patch"
        )
    
    # TODO: Apply patch to working tree
    # This would integrate with git_utils to apply the patch
    
    # Update issue state
    issue.pr_state = "staged"
    db.commit()
    
    return {"message": "Issue staged successfully"}


@router.post("/issues/{issue_id}/apply")
async def apply_issue(issue_id: int, db: Session = Depends(get_db)):
    """Apply an issue's patch immediately (admin only)"""
    
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    
    if not issue.can_auto_apply:
        raise HTTPException(
            status_code=400,
            detail="Issue cannot be auto-applied"
        )
    
    # TODO: Apply patch and commit
    # This would integrate with git_utils
    
    # Update issue state
    issue.pr_state = "committed"
    issue.state = "resolved"
    db.commit()
    
    return {"message": "Issue applied successfully"}