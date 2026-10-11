"""Pydantic API response models."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    uploaded_at: datetime
    file_size_bytes: int
    total_entries: int
    parsed_entries: int
    unparsed_entries: int


class LogEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    line_number: int
    timestamp: datetime | None
    severity: str | None
    message: str
    raw_line: str
    parsed: bool


class PaginatedEntriesResponse(BaseModel):
    items: list[LogEntryResponse]
    page: int
    page_size: int
    total: int
    total_pages: int
