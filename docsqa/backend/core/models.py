from sqlalchemy import Column, Integer, String, Text, Boolean, TIMESTAMP, BIGINT, NUMERIC, ForeignKey, Index, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from enum import Enum


Base = declarative_base()


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


class File(Base):
    __tablename__ = "files"
    
    id = Column(Integer, primary_key=True)
    path = Column(Text, unique=True, nullable=False)
    sha = Column(Text, nullable=True)  # blob SHA
    title = Column(Text, nullable=True)
    lang = Column(Text, default="en")
    last_seen_commit = Column(Text, nullable=True)
    status = Column(String(20), default=FileStatus.ACTIVE.value)
    
    # Timestamps
    created_at = Column(TIMESTAMP, default=func.now())
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now())
    
    # Relationships
    issues = relationship("Issue", back_populates="file")


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    
    id = Column(Integer, primary_key=True)
    commit_sha = Column(Text, nullable=False)
    started_at = Column(TIMESTAMP, nullable=True)
    finished_at = Column(TIMESTAMP, nullable=True)
    source = Column(String(20), nullable=False)  # manual, scheduled, webhook
    status = Column(String(20), nullable=False)  # running, success, failed
    stats = Column(JSON, nullable=True)
    
    # LLM usage tracking
    llm_token_in = Column(BIGINT, default=0)
    llm_token_out = Column(BIGINT, default=0)
    llm_cost_estimate = Column(NUMERIC, default=0)
    
    # Timestamps
    created_at = Column(TIMESTAMP, default=func.now())
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now())
    
    # Relationships
    first_seen_issues = relationship("Issue", foreign_keys="Issue.first_seen_run_id", back_populates="first_seen_run")
    last_seen_issues = relationship("Issue", foreign_keys="Issue.last_seen_run_id", back_populates="last_seen_run")


class Issue(Base):
    __tablename__ = "issues"
    
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    rule_code = Column(Text, nullable=False)
    severity = Column(String(20), nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    snippet = Column(Text, nullable=True)
    
    # Line/column position
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    col_start = Column(Integer, nullable=True)
    col_end = Column(Integer, nullable=True)
    
    # Evidence and suggestions
    evidence = Column(JSON, nullable=True)
    proposed_snippet = Column(Text, nullable=True)
    suggested_patch = Column(Text, nullable=True)  # unified diff
    citations = Column(JSON, nullable=True)
    confidence = Column(NUMERIC, nullable=True)
    provenance = Column(JSON, nullable=False)  # ["rule"] | ["llm"] | ["rule","llm"]
    
    # Auto-apply capability
    can_auto_apply = Column(Boolean, nullable=False, default=False)
    
    # Issue lifecycle
    state = Column(String(20), default=IssueState.OPEN.value)
    first_seen_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False)
    last_seen_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False)
    
    # PR tracking
    pr_state = Column(String(20), default=PRState.NONE.value)
    pr_url = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(TIMESTAMP, default=func.now())
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now())
    
    # Relationships
    file = relationship("File", back_populates="issues")
    first_seen_run = relationship("AnalysisRun", foreign_keys=[first_seen_run_id], back_populates="first_seen_issues")
    last_seen_run = relationship("AnalysisRun", foreign_keys=[last_seen_run_id], back_populates="last_seen_issues")


class Rule(Base):
    __tablename__ = "rules"
    
    rule_code = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    category = Column(Text, nullable=False)
    default_severity = Column(Text, nullable=False)
    config = Column(JSON, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    
    # Timestamps
    created_at = Column(TIMESTAMP, default=func.now())
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now())


# Composite unique index on issues to prevent duplicates
Index('idx_unique_issue', Issue.file_id, Issue.rule_code, Issue.line_start, Issue.title, unique=True)