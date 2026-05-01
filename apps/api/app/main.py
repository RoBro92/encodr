from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import sessionmaker

from app.api.routes import router
from app.services.bulk_queue import BulkQueueExecutor, BulkQueueService
from app.services.orchestration import BackgroundOrchestrationLoop, OrchestrationService
from app.core import PasswordHashService, TokenService, load_auth_runtime_settings
from app.core.security import WorkerTokenService
from app.core.worker_auth import load_worker_auth_runtime_settings
from encodr_core.config import ConfigBundle, load_config_bundle
from encodr_core.probe import FFprobeClient
from encodr_db.runtime import LocalWorkerLoop, WorkerExecutionService, WorkerStatusTracker
from encodr_shared import UpdateCheckSettings, UpdateChecker, configure_component_logging, read_version

APP_VERSION = read_version()
logger = logging.getLogger("encodr.api")


def create_runtime_engine(database_dsn: str):
    options: dict[str, object] = {
        "future": True,
        "pool_pre_ping": True,
    }
    try:
        url = make_url(database_dsn)
    except Exception:
        url = None
    if url is not None and url.drivername.startswith("postgresql"):
        options.update(
            {
                "pool_size": 10,
                "max_overflow": 20,
                "pool_timeout": 30,
            }
        )
        logger.info(
            "configured database connection pool",
            extra={"pool_size": 10, "max_overflow": 20, "pool_timeout": 30},
        )
    return create_engine(database_dsn, **options)


def create_app(
    *,
    config_bundle: ConfigBundle | None = None,
    session_factory: sessionmaker | None = None,
    worker_execution_service: WorkerExecutionService | None = None,
    start_background_services: bool | None = None,
) -> FastAPI:
    should_start_background_services = (
        config_bundle is None if start_background_services is None else start_background_services
    )
    bundle = config_bundle or load_config_bundle()
    configure_component_logging(
        component="api",
        log_dir=bundle.app.data_dir / "logs",
        level=bundle.app.log_level.value,
        retention_days=bundle.app.diagnostics.retention_days,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if should_start_background_services:
            orchestration_loop = BackgroundOrchestrationLoop(
                orchestration_service=app.state.orchestration_service,
            )
            app.state.orchestration_loop = orchestration_loop
            orchestration_loop.start()
        try:
            yield
        finally:
            orchestration_loop = getattr(app.state, "orchestration_loop", None)
            if orchestration_loop is not None:
                orchestration_loop.stop()
                app.state.orchestration_loop = None

    app = FastAPI(
        title="encodr API",
        version=APP_VERSION,
        description="API service for the encodr media ingestion preparation platform.",
        lifespan=lifespan,
    )

    @app.exception_handler(SQLAlchemyTimeoutError)
    async def sqlalchemy_timeout_handler(request: Request, exc: SQLAlchemyTimeoutError) -> JSONResponse:
        logger.error("database connection pool exhausted", extra={"path": request.url.path}, exc_info=exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "The API is temporarily waiting for database connections. Please retry shortly."},
        )

    auth_runtime = load_auth_runtime_settings(bundle.app)
    worker_auth_runtime = load_worker_auth_runtime_settings(bundle.app)
    app.state.config_bundle = bundle
    app.state.app_version = APP_VERSION
    app.state.password_hasher = PasswordHashService(bundle.app.auth.password_hash_scheme)
    app.state.token_service = TokenService(auth_runtime)
    app.state.worker_token_service = WorkerTokenService()
    app.state.worker_auth_runtime = worker_auth_runtime
    app.state.update_checker = UpdateChecker(
        current_version=APP_VERSION,
        settings=UpdateCheckSettings(
            enabled=bundle.app.update.enabled,
            metadata_url=str(bundle.app.update.metadata_url) if bundle.app.update.metadata_url else None,
            channel=bundle.app.update.channel,
            timeout_seconds=bundle.app.update.check_timeout_seconds,
        ),
    )

    if session_factory is None:
        engine = create_runtime_engine(str(bundle.app.database.dsn))
        session_factory = sessionmaker(engine, future=True)
    app.state.session_factory = session_factory
    app.state.probe_client_factory = lambda: FFprobeClient(binary_path=bundle.app.media.ffprobe_path)
    app.state.bulk_queue_service = BulkQueueService(
        config_bundle=bundle,
        session_factory=session_factory,
        probe_client_factory=app.state.probe_client_factory,
    )
    app.state.bulk_queue_executor = BulkQueueExecutor(app.state.bulk_queue_service)
    app.state.worker_status_tracker = WorkerStatusTracker()
    app.state.local_worker_loop = LocalWorkerLoop(
        session_factory,
        bundle,
        execution_service=worker_execution_service,
        status_tracker=app.state.worker_status_tracker,
    )
    app.state.orchestration_service = OrchestrationService(
        config_bundle=bundle,
        session_factory=session_factory,
        probe_client_factory=app.state.probe_client_factory,
    )
    app.state.orchestration_loop = None

    app.include_router(router, prefix=bundle.app.api.base_path)
    return app


app = create_app()
