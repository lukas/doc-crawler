from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import Issue, File
from core.schemas import PRCreate, PRResponse, CommitStrategy

router = APIRouter()


@router.post("/prs", response_model=PRResponse)
async def create_pr(pr_data: PRCreate, db: Session = Depends(get_db)):
    """Create a GitHub PR with selected issues"""
    
    # Get issues with their files
    issues = db.query(Issue).join(File).filter(
        Issue.id.in_(pr_data.issue_ids)
    ).all()
    
    if not issues:
        raise HTTPException(status_code=404, detail="No issues found")
    
    # Validate that all issues can be auto-applied
    non_auto_apply = [i for i in issues if not i.can_auto_apply]
    auto_apply_count = len(issues) - len(non_auto_apply)
    
    if non_auto_apply and not pr_data.open_draft:
        raise HTTPException(
            status_code=400,
            detail=f"{len(non_auto_apply)} issues cannot be auto-applied. Use draft mode."
        )
    
    # Group issues by file
    files_with_issues = {}
    for issue in issues:
        file_path = issue.file.path
        if file_path not in files_with_issues:
            files_with_issues[file_path] = []
        files_with_issues[file_path].append(issue)
    
    try:
        # TODO: Implement actual GitHub PR creation
        # This would:
        # 1. Create a new branch
        # 2. Apply patches according to commit strategy
        # 3. Push branch
        # 4. Create PR with proper description
        
        pr_url = f"https://github.com/wandb/docs/pull/12345"  # Mock URL
        
        # Update issue states
        for issue in issues:
            if issue.can_auto_apply:
                issue.pr_state = "pr_opened"
                issue.pr_url = pr_url
        
        db.commit()
        
        # Generate PR description
        pr_description = _generate_pr_description(
            issues, files_with_issues, pr_data.commit_strategy
        )
        
        return PRResponse(
            pr_url=pr_url,
            branch_name=pr_data.branch_name,
            issue_count=len(issues),
            auto_apply_count=auto_apply_count,
            manual_review_count=len(non_auto_apply)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create PR: {str(e)}"
        )


def _generate_pr_description(issues: List[Issue], files_with_issues: Dict[str, List[Issue]],
                           commit_strategy: CommitStrategy) -> str:
    """Generate PR description with issue details"""
    
    # Count by rule and severity
    rule_counts = {}
    severity_counts = {}
    
    for issue in issues:
        rule_counts[issue.rule_code] = rule_counts.get(issue.rule_code, 0) + 1
        severity_counts[issue.severity] = severity_counts.get(issue.severity, 0) + 1
    
    # Build description
    description_parts = [
        "## Docs QA Automated Fixes",
        "",
        "**Summary**",
        f"- {len(issues)} total fixes across {len(files_with_issues)} files",
    ]
    
    # Add severity breakdown
    for severity in ["critical", "high", "medium", "low"]:
        count = severity_counts.get(severity, 0)
        if count > 0:
            description_parts.append(f"- {count} {severity} severity issues")
    
    # Add rule breakdown
    description_parts.extend([
        "",
        "**Rules Applied**",
    ])
    
    for rule_code, count in sorted(rule_counts.items()):
        description_parts.append(f"- {rule_code}: {count} fixes")
    
    # Add checklist
    description_parts.extend([
        "",
        "**Checklist**",
        "- [ ] I reviewed clarity edits (no semantic change)",
        "- [ ] Accuracy changes cite catalogs or adjacent docs", 
        "- [ ] Link checks passed",
        "",
        "<details><summary>Per-file changes</summary>",
        ""
    ])
    
    # Add file details
    for file_path, file_issues in files_with_issues.items():
        file_rule_codes = list(set(issue.rule_code for issue in file_issues))
        description_parts.extend([
            f"### {file_path}",
            f"Rules: {', '.join(file_rule_codes)}",
            f"Issues: {len(file_issues)}",
            ""
        ])
        
        # Add citations if any
        all_citations = []
        for issue in file_issues:
            if issue.citations:
                all_citations.extend(issue.citations)
        
        if all_citations:
            description_parts.append("Citations:")
            for citation in all_citations[:3]:  # Limit to first 3
                if citation.get('type') == 'catalog':
                    description_parts.append(f"- catalog: {citation.get('key', 'N/A')}")
                elif citation.get('type') == 'file':
                    path = citation.get('path', 'N/A')
                    lines = f" lines {citation.get('line_start', '')}-{citation.get('line_end', '')}" if citation.get('line_start') else ""
                    description_parts.append(f"- file: {path}{lines}")
        
        description_parts.append("")
    
    description_parts.extend([
        "</details>",
        "",
        "🤖 Generated with [Claude Code](https://claude.ai/code)",
        "",
        "Co-Authored-By: Claude <noreply@anthropic.com>"
    ])
    
    return "\n".join(description_parts)


@router.get("/prs/preview")
async def preview_pr_description(
    issue_ids: List[int],
    commit_strategy: CommitStrategy = CommitStrategy.ONE_PER_FILE,
    db: Session = Depends(get_db)
):
    """Preview what the PR description would look like"""
    
    issues = db.query(Issue).join(File).filter(
        Issue.id.in_(issue_ids)
    ).all()
    
    if not issues:
        raise HTTPException(status_code=404, detail="No issues found")
    
    files_with_issues = {}
    for issue in issues:
        file_path = issue.file.path
        if file_path not in files_with_issues:
            files_with_issues[file_path] = []
        files_with_issues[file_path].append(issue)
    
    description = _generate_pr_description(issues, files_with_issues, commit_strategy)
    
    return {
        "description": description,
        "issue_count": len(issues),
        "file_count": len(files_with_issues),
        "auto_apply_count": sum(1 for i in issues if i.can_auto_apply),
        "manual_review_count": sum(1 for i in issues if not i.can_auto_apply)
    }