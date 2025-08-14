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


# Global database instance
db = Database()


def get_db() -> Generator[Session, None, None]:
    """Dependency for FastAPI endpoints"""
    with db.get_session() as session:
        yield session


def init_db():
    """Initialize database with tables"""
    db.create_tables()