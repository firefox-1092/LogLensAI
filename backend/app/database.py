"""Database engine and request-scoped SQLAlchemy sessions."""

import os
from collections.abc import Generator

from fastapi import Request
from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def create_database_engine(database_url: str) -> Engine:
    """Create an engine, using one shared connection for in-memory SQLite tests."""
    options: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
        if database_url in {"sqlite://", "sqlite:///:memory:", "sqlite+pysqlite:///:memory:"}:
            options["poolclass"] = StaticPool
    return create_engine(database_url, **options)


def database_url_from_environment() -> str:
    """Build a PostgreSQL URL without requiring URL-escaped passwords in .env."""
    url = URL.create(
        drivername="postgresql+psycopg",
        username=os.getenv("POSTGRES_USER", "loglens"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
        host="127.0.0.1",
        port=int(os.getenv("POSTGRES_HOST_PORT", "5433")),
        database=os.getenv("POSTGRES_DB", "loglens"),
    )
    return url.render_as_string(hide_password=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    """Yield a session from the current app's session factory."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session
