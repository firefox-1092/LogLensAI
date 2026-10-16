from datetime import datetime

import pytest

from backend.app.parser import MAX_JSON_RECORDS, StructuredLogLimitError, parse_json_text, parse_log_text


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


@pytest.mark.parametrize(
    ("status", "severity"),
    [("200", "INFO"), ("404", "WARN"), ("500", "ERROR")],
)
def test_apache_access_log_parses_status_severity_and_raw_source(status, severity) -> None:
    raw = (
        '66.249.66.194 - - [22/Jan/2019:05:18:41 +0330] '
        f'"GET /some/path HTTP/1.1" {status} 2138 '
        '"https://example.com/" "Mozilla/5.0 (X11; Linux x86_64)" "-"'
    )

    entry = parse_log_text(raw)[0]

    assert entry.parsed is True
    assert entry.line_number == 1
    assert entry.timestamp.isoformat() == "2019-01-22T05:18:41+03:30"
    assert entry.timestamp.utcoffset().total_seconds() == 3.5 * 60 * 60
    assert entry.severity == severity
    assert "client_ip=66.249.66.194" in entry.message
    assert f"HTTP {status}" in entry.message
    assert "GET /some/path HTTP/1.1" in entry.message
    assert "response_size=2138 bytes" in entry.message
    assert "referer=https://example.com/" in entry.message
    assert "user_agent=Mozilla/5.0 (X11; Linux x86_64)" in entry.message
    assert entry.raw_line == raw


def test_access_log_handles_escaped_quotes_missing_fields_and_unknown_size() -> None:
    raw = '192.0.2.1 - - [22/Jan/2019:05:18:41 -0430] "GET /hello HTTP/1.1" 204 - "-" "Agent \\"quoted\\""'

    entry = parse_log_text(raw)[0]

    assert entry.parsed is True
    assert entry.timestamp.utcoffset().total_seconds() == -(4.5 * 60 * 60)
    assert "response_size=bytes unavailable" in entry.message
    assert 'user_agent=Agent "quoted"' in entry.message
    assert entry.raw_line == raw


def test_access_log_allows_omitted_optional_fields_and_request_dash() -> None:
    entry = parse_log_text(
        '192.0.2.8 - - [22/Jan/2019:05:18:41 +0000] "-" 301 0'
    )[0]

    assert entry.parsed is True
    assert entry.severity == "INFO"
    assert "request unavailable" in entry.message
    assert "referer=" not in entry.message
    assert "user_agent=" not in entry.message


def test_access_log_retains_malformed_request_target_without_losing_access_record() -> None:
    raw = (
        '198.51.100.7 - - [22/Jan/2019:05:18:41 +0000] '
        '"GET /path with spaces HTTP/1.1" 400 166 "-" "scanner"'
    )

    entry = parse_log_text(raw)[0]

    assert entry.parsed is True
    assert entry.severity == "WARN"
    assert "GET /path with spaces HTTP/1.1" in entry.message
    assert entry.raw_line == raw


@pytest.mark.parametrize(
    "raw",
    [
        '999.0.0.1 - - [22/Jan/2019:05:18:41 +0000] "GET / HTTP/1.1" 200 12',
        '192.0.2.1 - - [32/Jan/2019:05:18:41 +0000] "GET / HTTP/1.1" 200 12',
        '192.0.2.1 - - [22/Jan/2019:05:18:41 +0000] "GET / HTTP/1.1" 600 12',
        '192.0.2.1 - - [22/Jan/2019:05:18:41 +0000] "GET / HTTP/1.1" 500 nope',
        '192.0.2.1 - - [22/Jan/2019:05:18:41 +0000] "not a request" 500 12',
    ],
)
def test_malformed_access_log_is_preserved_as_unparsed(raw) -> None:
    entry = parse_log_text(raw)[0]

    assert entry.parsed is False
    assert entry.timestamp is None
    assert entry.severity is None
    assert entry.message == raw
    assert entry.raw_line == raw


def test_jsonl_parses_common_aliases_preserves_raw_and_unicode():
    contents = '{"@timestamp":"2026-10-11T10:00:00Z","log_level":"error","event":"café ☕"}\n'
    result = parse_json_text(contents)
    assert len(result) == 1
    assert result[0].timestamp.isoformat() == "2026-10-11T10:00:00"
    assert result[0].severity == "ERROR"
    assert result[0].message == "café ☕"
    assert result[0].raw_line == contents.rstrip("\n")
    assert result[0].line_number == 1 and result[0].parsed is True


def test_json_missing_fields_and_unknown_severity_are_not_invented():
    result = parse_json_text('{"severity":"notice","payload":7}\n{"msg":"hello"}\n')
    assert result[0].severity is None
    assert result[0].timestamp is None
    assert result[0].parsed is True
    assert result[0].message == '{"severity":"notice","payload":7}'
    assert result[1].message == "hello"
    assert result[1].severity is None and result[1].timestamp is None
    date_only = parse_json_text('{"timestamp":"2026-10-11","message":"date only"}')[0]
    assert date_only.timestamp is None


def test_json_document_array_preserves_starting_lines_and_order():
    contents = '[\n  {"time":"2026-10-11 10:00:00","level":"warning","message":"first"},\n\n  {"timestamp":"2026-10-11T10:00:02","severity":"INFO","msg":"second"}\n]\n'
    result = parse_json_text(contents, document=True)
    assert [entry.line_number for entry in result] == [2, 4]
    assert [entry.message for entry in result] == ["first", "second"]
    assert result[0].severity == "WARN"
    assert result[0].raw_line.startswith('{"time"')


def test_compact_json_array_remains_one_unparsed_physical_record():
    raw = '[{"message":"first"},{"message":"second"}]'
    result = parse_json_text(raw, document=True)
    assert len(result) == 1
    assert result[0].parsed is False
    assert result[0].line_number == 1
    assert result[0].raw_line == raw


def test_jsonl_keeps_malformed_lines_unparsed_and_in_order():
    result = parse_json_text('{"message":"ok"}\nnot-json\n{"msg":"also ok"}\n')
    assert [entry.line_number for entry in result] == [1, 2, 3]
    assert [entry.parsed for entry in result] == [True, False, True]
    assert result[1].raw_line == "not-json"


def test_empty_json_and_malformed_document_are_handled_without_data_loss():
    assert parse_json_text(" \n\t", document=True) == []
    result = parse_json_text('{\n "message": "unterminated"', document=True)
    assert result and all(not entry.parsed for entry in result)


def test_structured_json_record_count_is_bounded():
    with pytest.raises(StructuredLogLimitError):
        parse_json_text('{"msg":"x"}\n' * (MAX_JSON_RECORDS + 1))
