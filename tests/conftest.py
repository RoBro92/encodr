from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

for package_path in (
    REPO_ROOT / "packages" / "core",
    REPO_ROOT / "packages" / "shared",
    REPO_ROOT / "packages" / "db",
    REPO_ROOT / "apps" / "worker",
):
    path_as_text = str(package_path)
    if path_as_text not in sys.path:
        sys.path.insert(0, path_as_text)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        path = Path(str(item.fspath))
        if "tests/unit/" in path.as_posix():
            item.add_marker(pytest.mark.unit)
        elif "tests/integration/" in path.as_posix():
            item.add_marker(pytest.mark.integration)
        elif "tests/e2e/" in path.as_posix():
            item.add_marker(pytest.mark.e2e)
