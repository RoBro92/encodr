from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from encodr_core.config import ConfigBundle, load_config_bundle

API_APP_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"


@dataclass(frozen=True, slots=True)
class ApiTestContext:
    client: TestClient
    session_factory: sessionmaker
    bundle: ConfigBundle
    app: object


@contextmanager
def import_api_module(module_name: str) -> Iterator[ModuleType]:
    existing_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "app" or name.startswith("app.")
    }
    for name in list(existing_modules):
        sys.modules.pop(name, None)

    sys.path.insert(0, str(API_APP_ROOT))
    try:
        yield importlib.import_module(module_name)
    finally:
        if str(API_APP_ROOT) in sys.path:
            sys.path.remove(str(API_APP_ROOT))
        for name in [name for name in sys.modules if name == "app" or name.startswith("app.")]:
            sys.modules.pop(name, None)
        sys.modules.update(existing_modules)


def create_test_api_context(
    *,
    repo_root: Path,
    session_factory: sessionmaker,
    auth_secret: str = "test-auth-secret-with-sufficient-length",
    bundle: ConfigBundle | None = None,
    worker_execution_service: Any | None = None,
) -> ApiTestContext:
    if bundle is None:
        bundle = load_config_bundle(project_root=repo_root)

    import os

    old_secret = os.environ.get("ENCODR_AUTH_SECRET")
    os.environ["ENCODR_AUTH_SECRET"] = auth_secret
    try:
        with import_api_module("app.main") as app_main:
            app = app_main.create_app(
                config_bundle=bundle,
                session_factory=session_factory,
                worker_execution_service=worker_execution_service,
            )
            client = TestClient(app)
    finally:
        if old_secret is None:
            os.environ.pop("ENCODR_AUTH_SECRET", None)
        else:
            os.environ["ENCODR_AUTH_SECRET"] = old_secret

    return ApiTestContext(client=client, session_factory=session_factory, bundle=bundle, app=app)


def load_api_security_module():
    with import_api_module("app.core.security") as module:
        return module


def load_api_auth_module():
    with import_api_module("app.core.auth") as module:
        return module


def load_api_worker_auth_module():
    with import_api_module("app.core.worker_auth") as module:
        return module
