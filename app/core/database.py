"""SQLAlchemy 2.0 sync engine and session factory (psycopg v3 driver)."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a scoped DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
