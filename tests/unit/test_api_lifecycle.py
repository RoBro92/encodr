from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.helpers.api import create_test_api_context, import_api_module
from tests.helpers.db import create_schema_session_factory


def test_importing_api_main_does_not_start_orchestration_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENCODR_AUTH_SECRET", "test-auth-secret-with-sufficient-length")
    monkeypatch.setenv("ENCODR_WORKER_REGISTRATION_SECRET", "test-worker-secret-with-sufficient-length")
    before = _orchestration_thread_ids()

    with import_api_module("app.main") as app_main:
        assert app_main.app.state.orchestration_loop is None
        assert _orchestration_thread_ids() == before

    assert _orchestration_thread_ids() == before


def test_orchestration_loop_uses_lifespan(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> None:
    monkeypatch.setenv("ENCODR_AUTH_SECRET", "test-auth-secret-with-sufficient-length")
    monkeypatch.setenv("ENCODR_WORKER_REGISTRATION_SECRET", "test-worker-secret-with-sufficient-length")
    _, session_factory = create_schema_session_factory()
    events: list[str] = []

    class FakeBackgroundOrchestrationLoop:
        def __init__(self, *, orchestration_service) -> None:
            self.orchestration_service = orchestration_service

        def start(self) -> None:
            events.append("started")

        def stop(self) -> None:
            events.append("stopped")

    with import_api_module("app.main") as app_main:
        monkeypatch.setattr(app_main, "BackgroundOrchestrationLoop", FakeBackgroundOrchestrationLoop)
        app = app_main.create_app(
            config_bundle=app_main.load_config_bundle(project_root=repo_root),
            session_factory=session_factory,
            start_background_services=True,
        )

        assert app.state.orchestration_loop is None
        with TestClient(app):
            assert events == ["started"]
            assert app.state.orchestration_loop is not None

        assert events == ["started", "stopped"]
        assert app.state.orchestration_loop is None


def test_test_api_context_does_not_start_background_services(repo_root: Path) -> None:
    _, session_factory = create_schema_session_factory()
    context = create_test_api_context(repo_root=repo_root, session_factory=session_factory)

    assert context.app.state.orchestration_loop is None
    context.client.close()


def test_background_orchestration_loop_stop_joins_worker_thread() -> None:
    with import_api_module("app.services.orchestration") as orchestration:
        ran = threading.Event()

        class CountingService:
            def run_once(self) -> None:
                ran.set()

        loop = orchestration.BackgroundOrchestrationLoop(
            orchestration_service=CountingService(),
            poll_interval_seconds=60,
        )
        thread: threading.Thread | None = None
        try:
            loop.start()
            assert ran.wait(timeout=1)
            thread = loop._thread
            assert thread is not None
            assert thread.is_alive()
        finally:
            loop.stop()

        assert thread is not None
        assert not thread.is_alive()
        assert loop._thread is None


def _orchestration_thread_ids() -> set[int]:
    return {
        thread.ident
        for thread in threading.enumerate()
        if thread.name == "encodr-orchestration" and thread.is_alive() and thread.ident is not None
    }
