"""Application entrypoint: wiring, lifespan, middleware, error shape."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import dependencies as deps
from app.api.v1.routes import batch, fines, health
from app.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db import audit as audit_db

settings = get_settings()
setup_logging(settings.log_level)
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    audit_enabled = audit_db.init_db(settings)
    log.info(
        "service starting",
        extra={
            "env": settings.app_env,
            "version": settings.app_version,
            "mock_providers": settings.mock_providers,
            "audit_db": audit_enabled,
        },
    )
    yield
    try:
        await deps.cache.close()
    except Exception:
        pass
    log.info("service stopping")


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.state.limiter = deps.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
        log.exception("unhandled error", extra={"path": request.url.path})
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    app.include_router(health.router)
    app.include_router(fines.router, prefix=settings.api_prefix)
    app.include_router(batch.router, prefix=settings.api_prefix)
    return app


app = create_app()
