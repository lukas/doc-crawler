"""Tests for API endpoints"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from docsqa.backend.app import app
from docsqa.backend.core.models import Base, Rule, File, AnalysisRun
from docsqa.backend.core.models import RunStatus, RunSource
from docsqa.backend.core.db import get_db


# Test database setup
@pytest.fixture
def test_engine():
    """Create test database engine"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def test_session(test_engine):
    """Create test database session"""
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def test_client(test_engine):
    """Create test client with test database"""
    def get_test_db():
        Session = sessionmaker(bind=test_engine)
        session = Session()
        try:
            yield session
        finally:
            session.close()
    
    app.dependency_overrides[get_db] = get_test_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_health_endpoint(test_client):
    """Test health check endpoint"""
    response = test_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "docsqa-api"


def test_root_endpoint(test_client):
    """Test root endpoint"""
    response = test_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert data["docs"] == "/docs"


def test_list_issues_empty(test_client):
    """Test listing issues when none exist"""
    response = test_client.get("/api/issues")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_list_rules_empty(test_client):
    """Test listing rules when none exist"""
    response = test_client.get("/api/rules")
    assert response.status_code == 200
    data = response.json()
    assert data == []


def test_list_files_empty(test_client):
    """Test listing files when none exist"""
    response = test_client.get("/api/files")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_list_runs_empty(test_client):
    """Test listing runs when none exist"""
    response = test_client.get("/api/runs")
    assert response.status_code == 200
    data = response.json()
    assert data == []


def test_list_rules_with_data(test_client, test_engine):
    """Test listing rules with sample data"""
    # Add test rule to the test database
    Session = sessionmaker(bind=test_engine)
    session = Session()
    try:
        rule = Rule(
            rule_code="TEST_RULE",
            name="Test Rule",
            category="test",
            default_severity="high",
            config={}
        )
        session.add(rule)
        session.commit()
    finally:
        session.close()
    
    response = test_client.get("/api/rules")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["rule_code"] == "TEST_RULE"
    assert data[0]["name"] == "Test Rule"


def test_list_files_with_data(test_client, test_engine):
    """Test listing files with sample data"""
    # Add test file to the test database
    Session = sessionmaker(bind=test_engine)
    session = Session()
    try:
        file_record = File(
            path="test/file.md",
            title="Test File",
            sha="abc123",
            last_seen_commit="main",
            status="active"
        )
        session.add(file_record)
        session.commit()
    finally:
        session.close()
    
    response = test_client.get("/api/files")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["path"] == "test/file.md"
    assert data["items"][0]["title"] == "Test File"


def test_list_runs_with_data(test_client, test_engine):
    """Test listing runs with sample data"""
    # Add test run to the test database
    Session = sessionmaker(bind=test_engine)
    session = Session()
    try:
        run = AnalysisRun(
            commit_sha="abc123",
            source=RunSource.MANUAL,
            status=RunStatus.SUCCESS,
            stats={"files_analyzed": 5}
        )
        session.add(run)
        session.commit()
    finally:
        session.close()
    
    response = test_client.get("/api/runs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["commit_sha"] == "abc123"
    assert data[0]["source"] == "manual"