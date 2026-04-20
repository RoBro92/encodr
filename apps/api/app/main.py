from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import router
from app.core import PasswordHashService, TokenService, load_auth_runtime_settings
from encodr_core.config import ConfigBundle, load_config_bundle


def create_app(
    *,
    config_bundle: ConfigBundle | None = None,
    session_factory: sessionmaker | None = None,
) -> FastAPI:
    bundle = config_bundle or load_config_bundle()
    app = FastAPI(
        title="encodr API",
        version="0.1.0",
        description="API service for the encodr media ingestion preparation platform.",
    )

    auth_runtime = load_auth_runtime_settings(bundle.app)
    app.state.config_bundle = bundle
    app.state.password_hasher = PasswordHashService(bundle.app.auth.password_hash_scheme)
    app.state.token_service = TokenService(auth_runtime)

    if session_factory is None:
        engine = create_engine(bundle.app.database.dsn, future=True)
        session_factory = sessionmaker(engine, future=True)
    app.state.session_factory = session_factory

    app.include_router(router, prefix=bundle.app.api.base_path)
    return app

app = create_app()
