"""Parse the initial timestamp/severity/message log format."""

import re
import json
from dataclasses import dataclass
from datetime import datetime, timezone

SEVERITIES = {"TRACE", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "FATAL", "CRITICAL"}
_LOG_LINE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<severity>TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\s+"
    r"(?P<message>.+?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedLogLine:
    line_number: int
    timestamp: datetime | None
    severity: str | None
    message: str
    raw_line: str
    parsed: bool


def parse_log_text(contents: str) -> list[ParsedLogLine]:
    """Parse non-empty physical lines and retain unsupported lines unchanged."""
    entries: list[ParsedLogLine] = []
    for line_number, raw_line in enumerate(contents.splitlines(), start=1):
        if not raw_line.strip():
            continue

        match = _LOG_LINE.fullmatch(raw_line)
        if match is None:
            entries.append(
                ParsedLogLine(line_number, None, None, raw_line, raw_line, False)
            )
            continue

        try:
            timestamp = datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            entries.append(
                ParsedLogLine(line_number, None, None, raw_line, raw_line, False)
            )
            continue

        severity = match.group("severity").upper()
        if severity == "WARNING":
            severity = "WARN"
        entries.append(
            ParsedLogLine(
                line_number=line_number,
                timestamp=timestamp,
                severity=severity,
                message=match.group("message"),
                raw_line=raw_line,
                parsed=True,
            )
        )
    return entries


_JSON_TIMESTAMP_KEYS = ("timestamp", "time", "@timestamp", "datetime")
_JSON_SEVERITY_KEYS = ("level", "severity", "log_level")
_JSON_MESSAGE_KEYS = ("message", "msg", "event")
_JSON_SEVERITIES = {"TRACE", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "FATAL", "CRITICAL"}
MAX_JSON_RECORDS = 50_000


class StructuredLogLimitError(ValueError):
    """Structured log input exceeded the per-upload record cap."""


def _case_insensitive_value(record: dict, names: tuple[str, ...]):
    values = {str(key).casefold(): value for key, value in record.items()}
    for name in names:
        value = values.get(name.casefold())
        if value is not None:
            return value
    return None


def _json_datetime(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    if not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", text):
        return None
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.utcoffset() is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _structured_entry(value, raw_line: str, line_number: int) -> ParsedLogLine:
    if not isinstance(value, dict):
        return ParsedLogLine(line_number, None, None, raw_line, raw_line, False)
    timestamp = _json_datetime(_case_insensitive_value(value, _JSON_TIMESTAMP_KEYS))
    severity_value = _case_insensitive_value(value, _JSON_SEVERITY_KEYS)
    severity = None
    if isinstance(severity_value, str):
        candidate = severity_value.strip().upper()
        if candidate in _JSON_SEVERITIES:
            severity = "WARN" if candidate == "WARNING" else candidate
    message_value = _case_insensitive_value(value, _JSON_MESSAGE_KEYS)
    if message_value is None:
        message = raw_line
    elif isinstance(message_value, str):
        message = message_value
    else:
        message = json.dumps(message_value, ensure_ascii=False, separators=(",", ":"))
    return ParsedLogLine(line_number, timestamp, severity, message, raw_line, True)


def _physical_line_json(contents: str) -> list[ParsedLogLine]:
    entries: list[ParsedLogLine] = []
    for line_number, raw_line in enumerate(contents.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            value = json.loads(raw_line)
            entry = _structured_entry(value, raw_line, line_number)
        except (json.JSONDecodeError, RecursionError):
            entries.append(ParsedLogLine(line_number, None, None, raw_line, raw_line, False))
            continue
        entries.append(entry)
        if len(entries) > MAX_JSON_RECORDS:
            raise StructuredLogLimitError(f"JSON uploads are limited to {MAX_JSON_RECORDS} non-empty records.")
    return entries


def _document_records(contents: str) -> list[tuple[object, str, int]]:
    """Decode a JSON object or array while preserving each record's source span."""
    decoder = json.JSONDecoder()
    start = len(contents) - len(contents.lstrip())
    if start == len(contents):
        return []
    records: list[tuple[object, str, int]] = []
    if contents[start] == "[":
        index = start + 1
        while True:
            while index < len(contents) and contents[index].isspace():
                index += 1
            if index >= len(contents):
                raise json.JSONDecodeError("Unterminated JSON array", contents, index)
            if contents[index] == "]":
                index += 1
                break
            record_start = index
            value, index = decoder.raw_decode(contents, index)
            line_number = contents.count("\n", 0, record_start) + 1
            records.append((value, contents[record_start:index], line_number))
            if len(records) > 1 and line_number == records[-2][2]:
                raise json.JSONDecodeError("Multiple records start on one physical line", contents, record_start)
            if len(records) > MAX_JSON_RECORDS:
                raise StructuredLogLimitError(f"JSON uploads are limited to {MAX_JSON_RECORDS} records.")
            while index < len(contents) and contents[index].isspace():
                index += 1
            if index < len(contents) and contents[index] == ",":
                index += 1
                while index < len(contents) and contents[index].isspace():
                    index += 1
                if index >= len(contents) or contents[index] == "]":
                    raise json.JSONDecodeError("Trailing comma in JSON array", contents, index)
                continue
            if index < len(contents) and contents[index] == "]":
                index += 1
                break
            raise json.JSONDecodeError("Expected comma or closing bracket", contents, index)
        if contents[index:].strip():
            raise json.JSONDecodeError("Extra data after JSON array", contents, index)
        return records
    value, end = decoder.raw_decode(contents, start)
    if contents[end:].strip():
        raise json.JSONDecodeError("Extra data after JSON object", contents, end)
    if isinstance(value, list):
        raise json.JSONDecodeError("Unexpected JSON array", contents, start)
    return [(value, contents[start:end], contents.count("\n", 0, start) + 1)]


def parse_json_text(contents: str, *, document: bool = False) -> list[ParsedLogLine]:
    """Parse JSONL physical records, or a JSON object/array with starting-line locations."""
    if not contents.strip():
        return []
    if document:
        try:
            records = _document_records(contents)
            return [_structured_entry(value, raw, line) for value, raw, line in records]
        except (json.JSONDecodeError, RecursionError):
            # Preserve recoverable individual lines as unparsed records for malformed documents.
            return _physical_line_json(contents)
    return _physical_line_json(contents)
