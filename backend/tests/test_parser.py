from datetime import datetime

import pytest

from backend.app.parser import parse_log_text


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        ("TRACE", "TRACE"),
        ("DEBUG", "DEBUG"),
        ("INFO", "INFO"),
        ("WARN", "WARN"),
        ("WARNING", "WARN"),
        ("ERROR", "ERROR"),
        ("FATAL", "FATAL"),
        ("CRITICAL", "CRITICAL"),
    ],
)
def test_parser_recognizes_supported_severities(severity: str, expected: str) -> None:
    entry = parse_log_text(f"2026-10-11 10:00:01 {severity} Example message")[0]

    assert entry.parsed is True
    assert entry.severity == expected
    assert entry.timestamp == datetime(2026, 10, 11, 10, 0, 1)
    assert entry.message == "Example message"


def test_malformed_lines_are_retained_and_later_lines_continue() -> None:
    entries = parse_log_text(
        "2026-10-11 10:00:01 INFO Started\nnot a supported record\n"
        "2026-10-11 10:00:03 ERROR Still running"
    )

    assert [entry.parsed for entry in entries] == [True, False, True]
    assert entries[1].line_number == 2
    assert entries[1].message == "not a supported record"
    assert entries[1].raw_line == "not a supported record"
    assert entries[1].parsed is False
    assert entries[1].timestamp is None
    assert entries[1].severity is None
    assert entries[2].line_number == 3


def test_parsed_entry_separates_message_from_original_line() -> None:
    raw_line = "2026-10-11 10:00:01 INFO Application started"

    entry = parse_log_text(raw_line)[0]

    assert entry.timestamp == datetime(2026, 10, 11, 10, 0, 1)
    assert entry.severity == "INFO"
    assert entry.message == "Application started"
    assert entry.raw_line == raw_line
    assert entry.line_number == 1
    assert entry.parsed is True


def test_invalid_calendar_timestamp_is_not_invented() -> None:
    entry = parse_log_text("2026-02-30 10:00:01 ERROR Invalid date")[0]

    assert entry.parsed is False
    assert entry.timestamp is None
    assert entry.severity is None
    assert entry.raw_line == "2026-02-30 10:00:01 ERROR Invalid date"


def test_empty_lines_are_skipped_without_shifting_source_line_numbers() -> None:
    entries = parse_log_text("\n2026-10-11 10:00:01 INFO Started\n\n")

    assert len(entries) == 1
    assert entries[0].line_number == 2
