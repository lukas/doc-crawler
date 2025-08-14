"""Debug test to understand database isolation issues"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from docsqa.backend.core.models import Base, Rule


def test_debug_engine_tables():
    """Test that tables are created in test engine"""
    # Create test engine
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    
    # Create session and verify tables exist
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # This should work if tables exist
        rules = session.query(Rule).all()
        print(f"SUCCESS: Found {len(rules)} rules in test database")
        assert len(rules) == 0  # Should be empty
    except Exception as e:
        print(f"ERROR: {e}")
        raise
    finally:
        session.close()


def test_debug_dependency_override(test_client):
    """Test to debug dependency override"""
    response = test_client.get("/health")
    assert response.status_code == 200
    print("Health endpoint works - test_client fixture is functional")