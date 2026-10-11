"""FastAPI application setup for LogLens."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from .ai import router as ai_router
from .database import create_database_engine, database_url_from_environment
from .models import Base
from .uploads import router as uploads_router

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _cors_origins() -> list[str]:
    """Read allowed browser origins from the environment, with Vite defaults."""
    configured = os.getenv(
        "LOG_LENS_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def create_app(database_url: str | None = None) -> FastAPI:
    """Build an app with an injectable database URL for isolated tests."""
    engine = create_database_engine(database_url or database_url_from_environment())
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        Base.metadata.create_all(bind=application.state.engine)
        yield
        application.state.engine.dispose()

    application = FastAPI(title="LogLens API", version="0.2.0", lifespan=lifespan)
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @application.get("/health", tags=["health"])
    def health_check() -> dict[str, str]:
        """Report that the API process is responding."""
        return {"status": "healthy"}

    @application.exception_handler(SQLAlchemyError)
    async def database_error_handler(
        _request: Request, _exception: SQLAlchemyError
    ) -> JSONResponse:
        """Return a safe database error without exposing SQL or credentials."""
        return JSONResponse(
            status_code=503,
            content={"detail": "Database operation failed. Check the local database connection."},
        )

    application.include_router(uploads_router)
    application.include_router(ai_router)
    return application


app = create_app()
