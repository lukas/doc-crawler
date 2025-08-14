"""Tests for API endpoints"""

import pytest


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


def test_list_rules(test_client):
    """Test listing rules API endpoint"""
    response = test_client.get("/api/rules")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Should have some default rules in the system
    if data:
        # Verify structure of rule objects
        rule = data[0]
        required_fields = ['rule_code', 'name', 'category', 'default_severity']
        for field in required_fields:
            assert field in rule


def test_list_files(test_client):
    """Test listing files API endpoint"""
    response = test_client.get("/api/files")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    assert isinstance(data["total"], int)
    # Verify structure if files exist
    if data["items"]:
        file_obj = data["items"][0]
        required_fields = ['path', 'title', 'sha', 'status']
        for field in required_fields:
            assert field in file_obj


def test_list_runs(test_client):
    """Test listing runs API endpoint"""
    response = test_client.get("/api/runs")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Verify structure if runs exist
    if data:
        run = data[0]
        required_fields = ['commit_sha', 'source', 'status']
        for field in required_fields:
            assert field in run


def test_rules_api_structure(test_client):
    """Test rules API response structure"""
    response = test_client.get("/api/rules")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    
    # Test that we can get categories
    response = test_client.get("/api/rules/categories")
    assert response.status_code == 200
    categories = response.json()
    assert isinstance(categories, list)


def test_files_api_pagination(test_client):
    """Test files API pagination works"""
    # Test basic pagination parameters
    response = test_client.get("/api/files?limit=5&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    
    # Test that pagination respects limits
    response = test_client.get("/api/files?limit=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) <= 1


def test_runs_api_functionality(test_client):
    """Test runs API basic functionality"""
    # Test basic listing works
    response = test_client.get("/api/runs")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    
    # Test limit parameter works
    response = test_client.get("/api/runs?limit=5")
    assert response.status_code == 200
    limited_data = response.json()
    assert isinstance(limited_data, list)
    assert len(limited_data) <= 5