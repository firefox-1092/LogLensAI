"""Pydantic API response models."""

from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class SeverityCounts(BaseModel):
    TRACE: int
    DEBUG: int
    INFO: int
    WARN: int
    ERROR: int
    FATAL: int
    CRITICAL: int


class ErrorPattern(BaseModel):
    fingerprint: str
    severity: str
    representative_message: str
    occurrences: int
    recurring: bool
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    representative_line_numbers: list[int]
    distinct_message_count: int


class TimelineBucket(BaseModel):
    timestamp: datetime
    entries: int


class DatasetTimeline(BaseModel):
    bucket_unit: Literal["minute", "hour", "day", "week", "none"]
    bucket_interval: int = 1
    buckets: list[TimelineBucket]


class DatasetAnalyticsResponse(BaseModel):
    total_entries: int
    parsed_entries: int
    unparsed_entries: int
    error_count: int
    warning_count: int
    unique_error_patterns: int
    recurring_error_patterns: int
    severity_counts: SeverityCounts
    error_patterns: list[ErrorPattern]
    timeline: DatasetTimeline


class AIChatHistoryTurn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=2000)

    @field_validator("question", "answer")
    @classmethod
    def history_must_have_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Conversation history must contain text.")
        return normalized


class AIChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    history: list[AIChatHistoryTurn] = Field(default_factory=list, max_length=4)

    @field_validator("question")
    @classmethod
    def question_must_have_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Question must contain non-whitespace text.")
        return normalized


class EvidenceReference(BaseModel):
    id: uuid.UUID
    line_number: int
    timestamp: datetime | None
    severity: str | None
    message: str
    raw_line: str | None = None
    parsed: bool


class AIChatResponse(BaseModel):
    answer: str
    evidence: list[EvidenceReference]
    cited_evidence: list[EvidenceReference] = Field(default_factory=list)
    completion_status: Literal["complete", "unknown"] = "complete"
