"""Pydantic API response models."""

from datetime import datetime
from typing import Annotated, Literal
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
    normalized_message_template: str
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
    error_count: int
    warning_count: int
    severity_counts: dict[str, int] = Field(default_factory=dict)


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


class InvestigationRequest(BaseModel):
    pattern_fingerprint: str = Field(min_length=16, max_length=16, pattern=r"^[a-f0-9]{16}$")
    include_source_context: bool = False


class InvestigationNodeDraft(BaseModel):
    id: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: Literal["observed_error", "evidence", "investigation_step", "diagnostic_branch", "verification", "conclusion"]
    status: Literal["observed", "suggested", "unverified"]
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    evidence_lines: list[int] = Field(default_factory=list, max_length=12)
    source_refs: list[str] = Field(default_factory=list, max_length=5)


class InvestigationEdge(BaseModel):
    source: str = Field(min_length=1, max_length=32)
    target: str = Field(min_length=1, max_length=32)
    label: str = Field(default="", max_length=80)


class InvestigationWorkflowDraft(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=600)
    nodes: list[InvestigationNodeDraft] = Field(min_length=1, max_length=12)
    edges: list[InvestigationEdge] = Field(default_factory=list, max_length=16)
    verification_steps: list[Annotated[str, Field(max_length=400)]] = Field(default_factory=list, max_length=8)
    limitations: list[Annotated[str, Field(max_length=400)]] = Field(default_factory=list, max_length=8)


class InvestigationEvidence(BaseModel):
    id: uuid.UUID
    line_number: int
    timestamp: datetime | None
    severity: str | None
    message: str
    raw_line: str | None = None
    parsed: bool


class InvestigationSourceEvidence(BaseModel):
    reference: str
    file_path: str
    chunk_index: int
    content: str


class InvestigationWorkflowResponse(InvestigationWorkflowDraft):
    status: Literal["ready_for_review"] = "ready_for_review"
    pattern_fingerprint: str
    evidence: list[InvestigationEvidence]
    source_context_used: bool = False
    source_evidence: list[InvestigationSourceEvidence] = Field(default_factory=list)
