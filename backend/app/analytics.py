"""Deterministic, dataset-scoped analytics for uploaded log entries."""

import hashlib
import ipaddress
import re
from collections import Counter
from datetime import datetime, timedelta
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LogEntry

MAX_ERROR_PATTERNS = 10
MAX_PATTERN_LINES = 10
_UUID = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")
_IP_CANDIDATE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_TIMESTAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b", re.I)
_SEVERITIES = ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL", "CRITICAL")
_ERROR_LEVELS = {"ERROR", "FATAL", "CRITICAL"}


def _replace_volatile_values(message: str, *, ip_placeholder: str = "<IP>") -> str:
    """Replace values already ignored by the grouping key, without changing other text."""
    normalized = _UUID.sub("<UUID>", message)

    def replace_ip(match: re.Match[str]) -> str:
        candidate = match.group(0)
        try:
            ipaddress.IPv4Address(candidate)
        except ipaddress.AddressValueError:
            return candidate
        return ip_placeholder

    normalized = _IP_CANDIDATE.sub(replace_ip, normalized)
    return _TIMESTAMP.sub("<TIMESTAMP>", normalized)


def normalize_error_message(message: str) -> str:
    """Normalize volatile identifiers while retaining meaningful values like status codes."""
    return " ".join(_replace_volatile_values(message).casefold().split())


def error_message_template(message: str) -> str:
    """Return a readable display template using the grouping algorithm's replacements."""
    return " ".join(_replace_volatile_values(message, ip_placeholder="<IP_ADDRESS>").split())


def _bucket_spec(first: datetime, last: datetime) -> tuple[str, int, timedelta]:
    span = max(last - first, timedelta(0))
    if span <= timedelta(hours=2):
        unit, base, seconds = "minute", timedelta(minutes=1), 60
    elif span <= timedelta(days=3):
        unit, base, seconds = "hour", timedelta(hours=1), 3600
    elif span <= timedelta(days=120):
        unit, base, seconds = "day", timedelta(days=1), 86400
    else:
        unit, base, seconds = "week", timedelta(days=7), 604800
    interval = max(1, ceil(span.total_seconds() / seconds / 95))
    return unit, interval, base * interval


def _bucket_start(value: datetime, unit: str, interval: int) -> datetime:
    if unit == "minute":
        return value.replace(second=0, microsecond=0, minute=value.minute // interval * interval)
    if unit == "hour":
        return value.replace(minute=0, second=0, microsecond=0, hour=value.hour // interval * interval)
    if unit == "day":
        day = value.replace(hour=0, minute=0, second=0, microsecond=0)
        return day - timedelta(days=(day.toordinal() - 1) % interval)
    week = value.replace(hour=0, minute=0, second=0, microsecond=0)
    week -= timedelta(days=week.weekday())
    return week - timedelta(days=((week.toordinal() - 1) // 7 % interval) * 7)


def build_dataset_analytics(db: Session, dataset_id) -> dict:
    """Stream only fields needed for deterministic counts, patterns, and timeline."""
    rows = db.execute(
        select(
            LogEntry.id,
            LogEntry.line_number,
            LogEntry.timestamp,
            LogEntry.severity,
            LogEntry.message,
            LogEntry.parsed,
        )
        .where(LogEntry.dataset_id == dataset_id)
        .order_by(LogEntry.line_number)
        .execution_options(yield_per=500)
    )

    severity_counts: Counter[str] = Counter()
    patterns: dict[tuple[str, str], dict] = {}
    timeline_counts: Counter[datetime] = Counter()
    timeline_error_counts: Counter[datetime] = Counter()
    timeline_warning_counts: Counter[datetime] = Counter()
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    total_entries = parsed_entries = unparsed_entries = errors = warnings = 0

    for _entry_id, line_number, timestamp, severity, message, parsed in rows:
        total_entries += 1
        if parsed:
            parsed_entries += 1
        else:
            unparsed_entries += 1

        normalized_severity = (severity or "").upper()
        if normalized_severity == "WARNING":
            normalized_severity = "WARN"
        if parsed and normalized_severity in _SEVERITIES:
            severity_counts[normalized_severity] += 1
        if normalized_severity in _ERROR_LEVELS:
            errors += 1
            normalized = normalize_error_message(message)
            key = (normalized_severity, normalized)
            pattern = patterns.get(key)
            if pattern is None:
                fingerprint = hashlib.sha256(f"{normalized_severity}\0{normalized}".encode()).hexdigest()[:16]
                pattern = {
                    "fingerprint": fingerprint,
                    "severity": normalized_severity,
                    "normalized_message": normalized,
                    "representative_message": message,
                    "occurrences": 0,
                    "first_timestamp": timestamp,
                    "last_timestamp": timestamp,
                    "line_numbers": [],
                    "variants": set(),
                }
                patterns[key] = pattern
            pattern["occurrences"] += 1
            pattern["variants"].add(message)
            if timestamp is not None:
                if pattern["first_timestamp"] is None or timestamp < pattern["first_timestamp"]:
                    pattern["first_timestamp"] = timestamp
                    pattern["representative_message"] = message
                if pattern["last_timestamp"] is None or timestamp > pattern["last_timestamp"]:
                    pattern["last_timestamp"] = timestamp
            if len(pattern["line_numbers"]) < MAX_PATTERN_LINES:
                pattern["line_numbers"].append(line_number)
        elif normalized_severity == "WARN":
            warnings += 1

        if timestamp is not None:
            if first_timestamp is None or timestamp < first_timestamp:
                first_timestamp = timestamp
            if last_timestamp is None or timestamp > last_timestamp:
                last_timestamp = timestamp

    if first_timestamp is not None and last_timestamp is not None:
        bucket_unit, bucket_interval, bucket_size = _bucket_spec(first_timestamp, last_timestamp)
        first_bucket = _bucket_start(first_timestamp, bucket_unit, bucket_interval)
        last_bucket = _bucket_start(last_timestamp, bucket_unit, bucket_interval)
        current = first_bucket
        while current <= last_bucket:
            timeline_counts[current] += 0
            current += bucket_size
    else:
        bucket_unit, bucket_interval, bucket_size = "none", 1, timedelta(0)
        first_bucket = last_bucket = None

    if first_timestamp is not None:
        timestamp_rows = db.execute(
            select(LogEntry.timestamp, LogEntry.severity)
            .where(LogEntry.dataset_id == dataset_id, LogEntry.timestamp.is_not(None))
            .execution_options(yield_per=500)
        )
        for timestamp, severity in timestamp_rows:
            bucket = _bucket_start(timestamp, bucket_unit, bucket_interval)
            timeline_counts[bucket] += 1
            normalized_severity = (severity or "").upper()
            if normalized_severity in _ERROR_LEVELS:
                timeline_error_counts[bucket] += 1
            elif normalized_severity in {"WARN", "WARNING"}:
                timeline_warning_counts[bucket] += 1

    ordered_patterns = sorted(
        patterns.values(),
        key=lambda item: (-item["occurrences"], item["severity"], item["normalized_message"]),
    )
    serialized_patterns = [
        {
            "fingerprint": item["fingerprint"],
            "severity": item["severity"],
            "normalized_message_template": error_message_template(item["representative_message"]),
            "representative_message": item["representative_message"],
            "occurrences": item["occurrences"],
            "recurring": item["occurrences"] >= 2,
            "first_timestamp": item["first_timestamp"],
            "last_timestamp": item["last_timestamp"],
            "representative_line_numbers": item["line_numbers"],
            "distinct_message_count": len(item["variants"]),
        }
        for item in ordered_patterns[:MAX_ERROR_PATTERNS]
    ]

    return {
        "total_entries": total_entries,
        "parsed_entries": parsed_entries,
        "unparsed_entries": unparsed_entries,
        "error_count": errors,
        "warning_count": warnings,
        "unique_error_patterns": len(patterns),
        "recurring_error_patterns": sum(item["occurrences"] >= 2 for item in patterns.values()),
        "severity_counts": {severity: severity_counts[severity] for severity in _SEVERITIES},
        "error_patterns": serialized_patterns,
        "timeline": {
            "bucket_unit": bucket_unit,
            "bucket_interval": bucket_interval,
            "buckets": [
                {
                    "timestamp": bucket,
                    "entries": count,
                    "error_count": timeline_error_counts[bucket],
                    "warning_count": timeline_warning_counts[bucket],
                }
                for bucket, count in sorted(timeline_counts.items())
            ],
        },
    }
