"""Optional audit persistence (PostgreSQL / SQLite via SQLAlchemy).

Disabled when `database_url` is empty. Writes are fire-and-forget: a DB
outage must never fail a challan lookup.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)

_engine = None
_SessionLocal = None


def init_db(settings: Settings) -> bool:
    """Create engine + table if a database_url is configured. Returns enabled flag."""
    global _engine, _SessionLocal
    if not settings.database_url:
        return False
    try:
        from sqlalchemy import DateTime, Float, Integer, String, create_engine
        from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

        class Base(DeclarativeBase):
            pass

        class QueryHistory(Base):
            __tablename__ = "query_history"
            id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
            vehicle_number: Mapped[str] = mapped_column(String(16), index=True)
            provider: Mapped[str] = mapped_column(String(32), default="")
            cache_hit: Mapped[int] = mapped_column(Integer, default=0)
            pending_count: Mapped[int] = mapped_column(Integer, default=0)
            pending_amount: Mapped[float] = mapped_column(Float, default=0.0)
            created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

        _engine = create_engine(settings.database_url, pool_pre_ping=True)
        Base.metadata.create_all(_engine)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
        # stash model for record() without re-importing sqlalchemy
        globals()["_QueryHistory"] = QueryHistory
        log.info("audit db enabled")
        return True
    except Exception as exc:
        log.warning("audit db disabled (init failed)", extra={"error": str(exc)})
        _engine = None
        _SessionLocal = None
        return False


def is_enabled() -> bool:
    return _engine is not None and _SessionLocal is not None


def record_query(
    vehicle_number: str,
    provider: str,
    cache_hit: bool,
    pending_count: int,
    pending_amount: float,
) -> None:
    if not is_enabled():
        return
    try:
        session = _SessionLocal()
        try:
            session.add(
                globals()["_QueryHistory"](
                    vehicle_number=vehicle_number,
                    provider=provider,
                    cache_hit=1 if cache_hit else 0,
                    pending_count=pending_count,
                    pending_amount=pending_amount,
                )
            )
            session.commit()
        finally:
            session.close()
    except Exception as exc:
        log.warning("audit write failed", extra={"error": str(exc)})
