from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from encodr_db import Base


def create_sqlite_engine(
    database_url: str = "sqlite+pysqlite:///:memory:",
    *,
    use_static_pool: bool = True,
) -> Engine:
    kwargs: dict[str, object] = {"future": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if use_static_pool:
            kwargs["poolclass"] = StaticPool
    return create_engine(database_url, **kwargs)


def create_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(engine, future=True, expire_on_commit=False)


def create_schema_session_factory(
    database_url: str = "sqlite+pysqlite:///:memory:",
) -> tuple[Engine, sessionmaker]:
    engine = create_sqlite_engine(database_url)
    Base.metadata.create_all(engine)
    return engine, create_session_factory(engine)


def upgrade_database_with_alembic(*, repo_root: Path, database_url: str) -> None:
    config = Config(str(repo_root / "packages" / "db" / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(repo_root / "packages" / "db" / "encodr_db" / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def create_migrated_session_factory(
    *,
    repo_root: Path,
    database_url: str,
) -> tuple[Engine, sessionmaker]:
    upgrade_database_with_alembic(repo_root=repo_root, database_url=database_url)
    engine = create_sqlite_engine(database_url, use_static_pool=False)
    return engine, create_session_factory(engine)


def list_table_names(engine: Engine) -> list[str]:
    return sorted(inspect(engine).get_table_names())
