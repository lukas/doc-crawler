from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum


# Enums
class FileStatus(str, Enum):
    ACTIVE = "active"
    DELETED = "deleted"


class RunSource(str, Enum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    WEBHOOK = "webhook"


class RunStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class IssueSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueState(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    IGNORED = "ignored"
    RESOLVED = "resolved"


class PRState(str, Enum):
    NONE = "none"
    STAGED = "staged"
    COMMITTED = "committed"
    PR_OPENED = "pr_opened"
    PR_MERGED = "pr_merged"
    PR_CLOSED = "pr_closed"


class CommitStrategy(str, Enum):
    SQUASH = "squash"
    ONE_PER_FILE = "one-per-file"
    ONE_PER_ISSUE = "one-per-issue"


# Base schemas
class BaseSchema(BaseModel):
    class Config:
        from_attributes = True


# File schemas
class FileBase(BaseSchema):
    path: str
    title: Optional[str] = None
    lang: str = "en"
    status: FileStatus = FileStatus.ACTIVE


class FileCreate(FileBase):
    sha: Optional[str] = None
    last_seen_commit: Optional[str] = None


class FileUpdate(BaseSchema):
    sha: Optional[str] = None
    title: Optional[str] = None
    last_seen_commit: Optional[str] = None
    status: Optional[FileStatus] = None


class FileResponse(FileBase):
    id: int
    sha: Optional[str]
    last_seen_commit: Optional[str]
    created_at: datetime
    updated_at: datetime
    issue_count: Optional[int] = 0


class FileDetail(FileResponse):
    content: Optional[str] = None
    headings: Optional[List[Dict[str, Any]]] = None
    issue_counts_by_severity: Optional[Dict[str, int]] = None


# Run schemas
class AnalysisRunBase(BaseSchema):
    commit_sha: str
    source: RunSource
    status: RunStatus


class AnalysisRunCreate(AnalysisRunBase):
    started_at: Optional[datetime] = None


class AnalysisRunUpdate(BaseSchema):
    status: Optional[RunStatus] = None
    finished_at: Optional[datetime] = None
    stats: Optional[Dict[str, Any]] = None
    llm_token_in: Optional[int] = None
    llm_token_out: Optional[int] = None
    llm_cost_estimate: Optional[float] = None


class AnalysisRunResponse(AnalysisRunBase):
    id: int
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    stats: Optional[Dict[str, Any]]
    llm_token_in: int = 0
    llm_token_out: int = 0
    llm_cost_estimate: float = 0
    created_at: datetime
    updated_at: datetime


# Citation schema
class Citation(BaseSchema):
    type: str  # "file", "catalog", "fact"
    path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    source: Optional[str] = None
    key: Optional[str] = None
    value: Optional[str] = None


# Issue schemas
class IssueBase(BaseSchema):
    rule_code: str
    severity: IssueSeverity
    title: str
    description: str
    snippet: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    col_start: Optional[int] = None
    col_end: Optional[int] = None


class IssueCreate(IssueBase):
    file_id: int
    evidence: Optional[Dict[str, Any]] = None
    proposed_snippet: Optional[str] = None
    suggested_patch: Optional[str] = None
    citations: Optional[List[Citation]] = None
    confidence: Optional[float] = None
    provenance: List[str]
    can_auto_apply: bool = False
    first_seen_run_id: int
    last_seen_run_id: int


class IssueUpdate(BaseSchema):
    state: Optional[IssueState] = None
    pr_state: Optional[PRState] = None
    pr_url: Optional[str] = None
    last_seen_run_id: Optional[int] = None


class IssueResponse(IssueBase):
    id: int
    file_id: int
    evidence: Optional[Dict[str, Any]]
    proposed_snippet: Optional[str]
    suggested_patch: Optional[str]
    citations: Optional[List[Citation]]
    confidence: Optional[float]
    provenance: List[str]
    can_auto_apply: bool
    state: IssueState
    first_seen_run_id: int
    last_seen_run_id: int
    pr_state: PRState
    pr_url: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    # Joined data
    file_path: Optional[str] = None
    file_title: Optional[str] = None


class IssueDetail(IssueResponse):
    file_content: Optional[str] = None
    rendered_context: Optional[str] = None


# Rule schemas
class RuleBase(BaseSchema):
    rule_code: str
    name: str
    category: str
    default_severity: str
    enabled: bool = True


class RuleCreate(RuleBase):
    config: Optional[Dict[str, Any]] = None


class RuleUpdate(BaseSchema):
    name: Optional[str] = None
    category: Optional[str] = None
    default_severity: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class RuleResponse(RuleBase):
    config: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime


# PR schemas
class PRCreate(BaseSchema):
    issue_ids: List[int]
    title: str
    branch_name: str
    commit_strategy: CommitStrategy = CommitStrategy.ONE_PER_FILE
    open_draft: bool = True


class PRResponse(BaseSchema):
    pr_url: str
    branch_name: str
    issue_count: int
    auto_apply_count: int
    manual_review_count: int


# Bulk operation schemas
class BulkIssueUpdate(BaseSchema):
    filter: Dict[str, Any]
    state: IssueState


# Pagination schemas
class PaginationParams(BaseSchema):
    page: int = Field(1, ge=1)
    limit: int = Field(50, ge=1, le=100)
    sort: Optional[str] = None


class PaginatedResponse(BaseSchema):
    items: List[Any]
    total: int
    page: int
    limit: int
    pages: int


# Filter schemas
class IssueFilters(BaseSchema):
    state: Optional[IssueState] = None
    severity: Optional[IssueSeverity] = None
    rule: Optional[str] = None
    file: Optional[str] = None
    q: Optional[str] = None  # Search query
    provenance: Optional[str] = None  # "rule", "llm", "both"
    has_patch: Optional[bool] = None
    can_auto_apply: Optional[bool] = None


class FileFilters(BaseSchema):
    path_prefix: Optional[str] = None
    q: Optional[str] = None  # Search query


# LLM suggestion schema (from LLM JSON response)
class LLMSuggestion(BaseSchema):
    type: str  # "text_edit", "code_edit", "delete", "insert", "question"
    rule_code: str  # "LLM_SPELL", "LLM_GRAMMAR", etc.
    severity: IssueSeverity
    confidence: float = Field(..., ge=0, le=1)
    title: str
    description: str
    file_path: str
    line_start: int
    line_end: int
    original_snippet: str
    proposed_snippet: str
    citations: List[Citation]
    tags: List[str]


class LLMResponse(BaseSchema):
    suggestions: List[LLMSuggestion]
    notes: Optional[str] = None