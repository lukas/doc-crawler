"""Tests for database functionality"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from docsqa.backend.core.models import Base, Rule, File, Issue, AnalysisRun
from docsqa.backend.core.models import RunStatus, RunSource, IssueState, IssueSeverity


@pytest.fixture
def test_engine():
    """Create a test database engine"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def test_session(test_engine):
    """Create a test database session"""
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.close()


def test_rule_model(test_session):
    """Test Rule model creation and queries"""
    rule = Rule(
        rule_code="TEST_RULE",
        name="Test Rule",
        category="test",
        default_severity="medium",
        config={"test": "value"}
    )
    
    test_session.add(rule)
    test_session.commit()
    
    # Query the rule back
    retrieved = test_session.query(Rule).filter(Rule.rule_code == "TEST_RULE").first()
    assert retrieved is not None
    assert retrieved.name == "Test Rule"
    assert retrieved.category == "test"
    assert retrieved.config == {"test": "value"}


def test_file_model(test_session):
    """Test File model creation and queries"""
    file_record = File(
        path="test/file.md",
        title="Test File",
        sha="abc123",
        last_seen_commit="main",
        status="active"
    )
    
    test_session.add(file_record)
    test_session.commit()
    
    # Query the file back
    retrieved = test_session.query(File).filter(File.path == "test/file.md").first()
    assert retrieved is not None
    assert retrieved.title == "Test File"
    assert retrieved.sha == "abc123"
    assert retrieved.status == "active"


def test_issue_model(test_session):
    """Test Issue model with relationships"""
    # Create a file first
    file_record = File(
        path="test/file.md",
        title="Test File", 
        sha="abc123",
        last_seen_commit="main",
        status="active"
    )
    test_session.add(file_record)
    test_session.flush()  # Get the ID
    
    # Create an analysis run
    run = AnalysisRun(
        commit_sha="def456",
        source=RunSource.MANUAL,
        status=RunStatus.SUCCESS,
        stats={}
    )
    test_session.add(run)
    test_session.flush()
    
    # Create an issue
    issue = Issue(
        file_id=file_record.id,
        rule_code="TEST_ISSUE",
        severity=IssueSeverity.HIGH,
        title="Test Issue",
        description="This is a test issue",
        state=IssueState.OPEN,
        first_seen_run_id=run.id,
        last_seen_run_id=run.id
    )
    
    test_session.add(issue)
    test_session.commit()
    
    # Test relationships
    retrieved_issue = test_session.query(Issue).first()
    assert retrieved_issue is not None
    assert retrieved_issue.file.path == "test/file.md"
    assert retrieved_issue.rule_code == "TEST_ISSUE"
    assert retrieved_issue.severity == IssueSeverity.HIGH


def test_analysis_run_model(test_session):
    """Test AnalysisRun model"""
    run = AnalysisRun(
        commit_sha="abc123",
        source=RunSource.SCHEDULED,
        status=RunStatus.RUNNING,
        stats={"files_analyzed": 10}
    )
    
    test_session.add(run)
    test_session.commit()
    
    retrieved = test_session.query(AnalysisRun).first()
    assert retrieved is not None
    assert retrieved.commit_sha == "abc123"
    assert retrieved.source == RunSource.SCHEDULED
    assert retrieved.status == RunStatus.RUNNING
    assert retrieved.stats == {"files_analyzed": 10}