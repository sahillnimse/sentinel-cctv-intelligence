from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from .config import settings

if settings.database_url.startswith("sqlite"):
    # 30 ingestion workers hold a session each for their lifetime; a bounded
    # pool starves the API (QueuePool limit reached). SQLite connections are
    # cheap file handles, so skip pooling entirely, and use WAL + busy_timeout
    # so concurrent writers don't hit "database is locked".
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()
else:
    engine = create_engine(settings.database_url, pool_size=40, max_overflow=20)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
