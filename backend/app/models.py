"""SQLAlchemy tables for uploaded datasets and their log entries."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid


class Base(DeclarativeBase):
    pass


class UploadedDataset(Base):
    __tablename__ = "uploads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    total_entries: Mapped[int] = mapped_column(Integer, nullable=False)
    parsed_entries: Mapped[int] = mapped_column(Integer, nullable=False)
    unparsed_entries: Mapped[int] = mapped_column(Integer, nullable=False)
    entries: Mapped[list["LogEntry"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class LogEntry(Base):
    __tablename__ = "log_entries"
    __table_args__ = (
        UniqueConstraint("dataset_id", "line_number", name="uq_log_entries_dataset_line"),
        Index("ix_log_entries_dataset_severity", "dataset_id", "severity"),
        Index("ix_log_entries_dataset_line", "dataset_id", "line_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_line: Mapped[str] = mapped_column(Text, nullable=False)
    parsed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    dataset: Mapped[UploadedDataset] = relationship(back_populates="entries")


class SourceContextChunk(Base):
    """A bounded, redacted code chunk explicitly uploaded for one dataset."""

    __tablename__ = "source_context_chunks"
    __table_args__ = (
        UniqueConstraint("dataset_id", "file_path", "chunk_index", name="uq_source_context_chunk"),
        Index("ix_source_context_dataset", "dataset_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
