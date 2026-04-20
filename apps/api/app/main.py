from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import router
from app.core import PasswordHashService, TokenService, load_auth_runtime_settings
from app.core.security import WorkerTokenService
from app.core.worker_auth import load_worker_auth_runtime_settings
from encodr_core.config import ConfigBundle, load_config_bundle
from encodr_core.probe import FFprobeClient
from encodr_db.runtime import LocalWorkerLoop, WorkerExecutionService, WorkerStatusTracker
from encodr_shared import UpdateCheckSettings, UpdateChecker, read_version

APP_VERSION = read_version()


def create_app(
    *,
    config_bundle: ConfigBundle | None = None,
    session_factory: sessionmaker | None = None,
    worker_execution_service: WorkerExecutionService | None = None,
) -> FastAPI:
    bundle = config_bundle or load_config_bundle()
    app = FastAPI(
        title="encodr API",
        version=APP_VERSION,
        description="API service for the encodr media ingestion preparation platform.",
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
        engine = create_engine(bundle.app.database.dsn, future=True)
        session_factory = sessionmaker(engine, future=True)
    app.state.session_factory = session_factory
    app.state.probe_client_factory = lambda: FFprobeClient(binary_path=bundle.app.media.ffprobe_path)
    app.state.worker_status_tracker = WorkerStatusTracker()
    app.state.local_worker_loop = LocalWorkerLoop(
        session_factory,
        bundle,
        execution_service=worker_execution_service,
        status_tracker=app.state.worker_status_tracker,
    )

    app.include_router(router, prefix=bundle.app.api.base_path)
    return app

app = create_app()
