"""Parse the initial timestamp/severity/message log format."""

import re
from dataclasses import dataclass
from datetime import datetime

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
