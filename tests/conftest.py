"""Pytest configuration and shared fixtures"""

import pytest
import os
import tempfile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Import after setting test environment
os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from docsqa.backend.core.models import Base
from docsqa.backend.core import db as db_module
from docsqa.backend.app import create_app


@pytest.fixture(scope="function")
def test_engine():
    """Create a test database engine for each test"""
    engine = create_engine(
        "sqlite:///:memory:", 
        echo=False,
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def test_session(test_engine):
    """Create a test database session"""
    Session = sessionmaker(bind=test_engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def test_app(test_engine):
    """Create a FastAPI test app with isolated database"""
    app = create_app(with_lifespan=False)
    
    # Create a session factory for the test
    TestSession = sessionmaker(bind=test_engine)
    
    def get_test_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()
    
    # Override the dependency function
    app.dependency_overrides[db_module.get_db] = get_test_db
    yield app
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def test_client(test_app):
    """Create a test client with isolated database"""
    with TestClient(test_app) as client:
        yield client