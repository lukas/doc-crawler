from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager
from typing import Generator
import os

from .config import get_database_url
from .models import Base


class Database:
    def __init__(self, database_url: str = None):
        self.database_url = database_url or get_database_url()
        
        # Use SQLite for development if postgres not available
        if "sqlite" in self.database_url.lower():
            self.engine = create_engine(
                self.database_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False
            )
        else:
            self.engine = create_engine(
                self.database_url,
                echo=False,
                pool_pre_ping=True,
                pool_recycle=300
            )
        
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
    
    def create_tables(self):
        """Create all tables"""
        Base.metadata.create_all(bind=self.engine)
    
    def drop_tables(self):
        """Drop all tables (for testing)"""
        Base.metadata.drop_all(bind=self.engine)
    
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Get a database session with automatic cleanup"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


# Global database instance - lazy initialization
_db_instance = None


def get_database_instance() -> Database:
    """Get the global database instance, creating it if needed"""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance


def get_db() -> Generator[Session, None, None]:
    """Dependency for FastAPI endpoints"""
    db = get_database_instance()
    with db.get_session() as session:
        yield session


# Legacy compatibility - use function instead of direct access
def db():
    return get_database_instance()


def init_db():
    """Initialize database with tables"""
    database = get_database_instance()
    database.create_tables()


def reset_db_instance():
    """Reset the global database instance (for testing)"""
    global _db_instance
    _db_instance = None