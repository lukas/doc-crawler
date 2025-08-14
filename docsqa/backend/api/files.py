from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from ..core.db import get_db
from ..core.models import File, Issue
from ..core.schemas import FileResponse, FileDetail, PaginatedResponse

router = APIRouter()


@router.get("/files", response_model=PaginatedResponse)
async def list_files(
    path_prefix: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """List files with filtering and pagination"""
    
    # Build query with issue counts
    query = db.query(
        File,
        func.count(Issue.id).label('issue_count')
    ).outerjoin(Issue).group_by(File.id)
    
    # Apply filters
    if path_prefix:
        query = query.filter(File.path.startswith(path_prefix))
    
    if q:
        search_filter = or_(
            File.path.ilike(f"%{q}%"),
            File.title.ilike(f"%{q}%")
        )
        query = query.filter(search_filter)
    
    # Apply ordering
    query = query.order_by(File.path)
    
    # Get total count
    total = query.count()
    
    # Apply pagination
    offset = (page - 1) * limit
    results = query.offset(offset).limit(limit).all()
    
    # Convert to response format
    file_responses = []
    for file, issue_count in results:
        response = FileResponse.from_orm(file)
        response.issue_count = issue_count
        file_responses.append(response)
    
    pages = (total + limit - 1) // limit
    
    return PaginatedResponse(
        items=file_responses,
        total=total,
        page=page,
        limit=limit,
        pages=pages
    )


@router.get("/files/{file_id}", response_model=FileDetail)
async def get_file(file_id: int, db: Session = Depends(get_db)):
    """Get detailed information about a specific file"""
    
    file = db.query(File).filter(File.id == file_id).first()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Get issue counts by severity
    issue_counts = db.query(
        Issue.severity,
        func.count(Issue.id).label('count')
    ).filter(
        Issue.file_id == file_id,
        Issue.state == 'open'
    ).group_by(Issue.severity).all()
    
    severity_counts = {severity: count for severity, count in issue_counts}
    
    # Build response
    response = FileDetail.from_orm(file)
    response.issue_counts_by_severity = severity_counts
    
    # Load file content if available
    try:
        # TODO: In real system, get content from git repository
        # For now, try to read from filesystem
        with open(file.path, 'r', encoding='utf-8') as f:
            response.content = f.read()
    except Exception:
        response.content = "Could not load file content"
    
    # Extract headings (simplified)
    if response.content:
        import re
        heading_matches = re.finditer(r'^(#+)\s+(.*)', response.content, re.MULTILINE)
        headings = []
        for match in heading_matches:
            level = len(match.group(1))
            text = match.group(2)
            line_num = response.content[:match.start()].count('\n') + 1
            headings.append({
                'level': level,
                'text': text,
                'line': line_num
            })
        response.headings = headings
    
    return response


@router.get("/files/{file_id}/issues", response_model=List[Dict[str, Any]])
async def get_file_issues(file_id: int, db: Session = Depends(get_db)):
    """Get all issues for a specific file"""
    
    file = db.query(File).filter(File.id == file_id).first()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    issues = db.query(Issue).filter(Issue.file_id == file_id).order_by(
        Issue.line_start, Issue.severity.desc()
    ).all()
    
    return [
        {
            "id": issue.id,
            "rule_code": issue.rule_code,
            "severity": issue.severity,
            "title": issue.title,
            "line_start": issue.line_start,
            "line_end": issue.line_end,
            "state": issue.state,
            "can_auto_apply": issue.can_auto_apply
        }
        for issue in issues
    ]