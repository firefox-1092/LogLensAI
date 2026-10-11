"""Application service that parses and persists one uploaded log dataset."""

from sqlalchemy.orm import Session

from .models import LogEntry, UploadedDataset
from .parser import parse_log_text


class EmptyLogFileError(ValueError):
    """Raised when a text file has no non-empty records to store."""


def persist_parsed_upload(
    db: Session, filename: str, raw_contents: bytes, text_contents: str
) -> UploadedDataset:
    """Save upload metadata and every non-empty parsed or unparsed line atomically."""
    parsed_lines = parse_log_text(text_contents)
    if not parsed_lines:
        raise EmptyLogFileError("The file contains no non-empty log lines.")

    parsed_count = sum(line.parsed for line in parsed_lines)
    dataset = UploadedDataset(
        filename=filename,
        file_size_bytes=len(raw_contents),
        total_entries=len(parsed_lines),
        parsed_entries=parsed_count,
        unparsed_entries=len(parsed_lines) - parsed_count,
    )
    dataset.entries = [
        LogEntry(
            line_number=line.line_number,
            timestamp=line.timestamp,
            severity=line.severity,
            message=line.message,
            raw_line=line.raw_line,
            parsed=line.parsed,
        )
        for line in parsed_lines
    ]
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset
