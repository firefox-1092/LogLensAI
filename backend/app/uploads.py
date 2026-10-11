"""Upload validation, parsing, and database persistence."""

import os
import uuid
from pathlib import PurePath

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import get_db
from .analytics import build_dataset_analytics
from .ingestion import EmptyLogFileError, persist_parsed_upload
from .models import LogEntry, UploadedDataset
from .parser import SEVERITIES
from .schemas import DatasetAnalyticsResponse, PaginatedEntriesResponse, UploadResponse

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
_CHUNK_SIZE = 64 * 1024
_MAX_FILENAME_LENGTH = 255


def maximum_upload_bytes() -> int:
    value = int(os.getenv("LOG_LENS_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    if value <= 0:
        raise RuntimeError("LOG_LENS_MAX_UPLOAD_BYTES must be a positive integer")
    return value


async def _read_bounded_upload(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = await upload.read(min(_CHUNK_SIZE, limit + 1 - total_bytes))
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > limit:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {limit} byte upload limit.",
            )
        chunks.append(chunk)
    if total_bytes == 0:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    return b"".join(chunks)


@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_log_file(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> UploadedDataset:
    """Validate, parse, and persist one .log or .txt file."""
    filename = file.filename or ""
    if not filename or len(filename) > _MAX_FILENAME_LENGTH:
        raise HTTPException(status_code=400, detail="Provide a filename up to 255 characters long.")
    if PurePath(filename).suffix.lower() not in {".log", ".txt"}:
        raise HTTPException(status_code=400, detail="Only .log and .txt files are accepted.")

    raw_contents = await _read_bounded_upload(file, maximum_upload_bytes())
    try:
        text_contents = raw_contents.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="The file must contain valid UTF-8 text.",
        ) from exc

    try:
        return persist_parsed_upload(db, filename, raw_contents, text_contents)
    except EmptyLogFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[UploadResponse])
def list_uploads(
    limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)
) -> list[UploadedDataset]:
    """Return the most recently uploaded datasets."""
    statement = select(UploadedDataset).order_by(
        UploadedDataset.uploaded_at.desc(), UploadedDataset.id
    ).limit(limit)
    return list(db.scalars(statement).all())


@router.get("/{upload_id}/entries", response_model=PaginatedEntriesResponse)
def list_entries(
    upload_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    line_number: int | None = Query(default=None, ge=1),
    severity: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
) -> PaginatedEntriesResponse:
    """Return entries for a dataset, optionally filtered and paginated."""
    try:
        dataset_id = uuid.UUID(upload_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="upload_id must be a valid UUID.") from exc

    if db.get(UploadedDataset, dataset_id) is None:
        raise HTTPException(status_code=404, detail="Upload not found.")

    conditions = [LogEntry.dataset_id == dataset_id]
    if line_number is not None:
        conditions.append(LogEntry.line_number == line_number)
    if severity:
        normalized_severity = severity.upper()
        if normalized_severity == "WARNING":
            normalized_severity = "WARN"
        if normalized_severity not in (SEVERITIES - {"WARNING"}):
            allowed = ", ".join(sorted(SEVERITIES - {"WARNING"}))
            raise HTTPException(status_code=422, detail=f"severity must be one of: {allowed}.")
        conditions.append(LogEntry.severity == normalized_severity)
    if q:
        conditions.append(func.lower(LogEntry.message).contains(q.lower(), autoescape=True))

    total = db.scalar(select(func.count()).select_from(LogEntry).where(*conditions)) or 0
    entries_statement = (
        select(LogEntry)
        .where(*conditions)
        .order_by(LogEntry.line_number)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list(db.scalars(entries_statement).all())
    total_pages = (total + page_size - 1) // page_size
    return PaginatedEntriesResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


@router.get("/{upload_id}/analytics", response_model=DatasetAnalyticsResponse)
def get_dataset_analytics(upload_id: str, db: Session = Depends(get_db)) -> dict:
    """Return deterministic counts and recurring-error patterns for one upload."""
    try:
        dataset_id = uuid.UUID(upload_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="upload_id must be a valid UUID.") from exc

    if db.get(UploadedDataset, dataset_id) is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    return build_dataset_analytics(db, dataset_id)
