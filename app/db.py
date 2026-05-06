"""SQLite database setup with WAL mode for concurrent reads/writes."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# `check_same_thread=False` is required because FastAPI uses threads.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Apply WAL + performance pragmas on every new connection.

    WAL allows concurrent readers + one writer (vs. default rollback journal).
    synchronous=NORMAL is safe with WAL and ~2x faster than FULL.
    busy_timeout makes writers wait instead of immediately failing on locks.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called once at app startup."""
    # Import models so they register with Base.metadata
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
