"""
StressForge Database — SQLAlchemy engine + session management.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=20,
    max_overflow=30,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency: yields a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables."""
    from app import models  # noqa: F401 — ensure models are imported
    Base.metadata.create_all(bind=engine)
