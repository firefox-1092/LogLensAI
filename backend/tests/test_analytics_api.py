from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend.app.analytics import MAX_ERROR_PATTERNS, error_message_template, normalize_error_message
from backend.app.main import create_app
from backend.app.models import UploadedDataset


# Pairwise labels are synthetic regression cases, not production-quality metrics.
CORRELATION_CORPUS = [
    (
        "IPv4 variation", "ERROR", "Connection to 192.0.2.10 timed out",
        "ERROR", "Connection to 198.51.100.8 timed out", True,
    ),
    (
        "case and whitespace", "ERROR", " Request   Failed to open file ",
        "ERROR", "request failed TO OPEN FILE", True,
    ),
    (
        "ISO timestamp variation", "ERROR", "Job failed at 2026-10-11 10:00:01",
        "ERROR", "Job failed at 2026-10-12T11:02:03.456Z", True,
    ),
    (
        "comma millisecond timestamps", "ERROR", "Job failed at 2026-10-11 10:00:01,123",
        "ERROR", "Job failed at 2026-10-11 10:00:01,987", True,
    ),
    (
        "UUID variation", "ERROR", "Request failed id=550e8400-e29b-41d4-a716-446655440000",
        "ERROR", "Request failed id=550e8400-e29b-41d4-a716-446655440001", True,
    ),
    (
        "labeled request IDs", "ERROR", "Lookup failed requestId=req-abc12345",
        "ERROR", "Lookup failed requestId=req-xyz98765", True,
    ),
    (
        "labeled correlation IDs", "ERROR", "Lookup failed correlation_id=corr-abc12345",
        "ERROR", "Lookup failed correlation_id=corr-xyz98765", True,
    ),
    (
        "labeled trace IDs", "ERROR", "Lookup failed trace-id=trace-abc12345",
        "ERROR", "Lookup failed trace-id=trace-xyz98765", True,
    ),
    (
        "IPv6 variation", "ERROR", "Connection to [2001:db8::1] timed out",
        "ERROR", "Connection to [2001:db8::2] timed out", True,
    ),
    (
        "HTTP statuses", "ERROR", "Request failed with HTTP 401",
        "ERROR", "Request failed with HTTP 500", False,
    ),
    (
        "database timeout vs authentication", "ERROR", "Database connection timed out",
        "ERROR", "Database authentication failed", False,
    ),
    (
        "refused vs timed out", "ERROR", "Connection refused by server",
        "ERROR", "Connection timed out waiting for server", False,
    ),
    ("severity difference", "ERROR", "Connection failed", "WARN", "Connection failed", False),
    (
        "meaningful numbers", "ERROR", "Batch processed 3 records",
        "ERROR", "Batch processed 4 records", False,
    ),
    (
        "invalid IPv4 values", "ERROR", "Connection to 999.999.999.998 failed",
        "ERROR", "Connection to 999.999.999.999 failed", False,
    ),
    (
        "invalid IPv6 values", "ERROR", "Connection to 2001:db8::gg failed",
        "ERROR", "Connection to 2001:db8::hh failed", False,
    ),
    (
        "different operations", "ERROR", "Failed to write user record",
        "ERROR", "Failed to read user record", False,
    ),
]


def _correlation_key(severity: str, message: str) -> tuple[str, str]:
    normalized_severity = severity.upper()
    if normalized_severity == "WARNING":
        normalized_severity = "WARN"
    return normalized_severity, normalize_error_message(message)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("LOG_LENS_MAX_UPLOAD_BYTES", "50000")
    app = create_app("sqlite://")
    with TestClient(app) as test_client:
        yield test_client


def upload(client: TestClient, name: str, contents: str) -> str:
    response = client.post(
        "/api/uploads",
        files={"file": (name, contents.encode(), "text/plain")},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_normalization_groups_volatile_values_but_preserves_status_codes() -> None:
    first = normalize_error_message(
        "Request failed 2026-10-11 10:00:01 from 192.168.0.1 id=550e8400-e29b-41d4-a716-446655440000 status 401"
    )
    second = normalize_error_message(
        " REQUEST   FAILED 2026-10-11T10:00:02 from 10.0.0.2 id=550e8400-e29b-41d4-a716-446655440001 status 401 "
    )
    other_status = normalize_error_message("Request failed status 500")

    assert first == second
    assert "status 401" in first
    assert normalize_error_message("Request failed status 401") != other_status


def test_display_template_uses_readable_placeholders_and_preserves_case() -> None:
    template = error_message_template("Connection to 192.168.1.10 timed out")

    assert template == "Connection to <IP_ADDRESS> timed out"
    assert error_message_template("Literal <IP> placeholder") == "Literal <IP> placeholder"


def test_display_template_normalizes_ipv6_request_ids_and_comma_timestamps() -> None:
    template = error_message_template(
        "Connect to [2001:db8::1] requestId=req-abc12345 at 2026-10-11 10:00:01,123"
    )

    assert template == "Connect to [<IP_ADDRESS>] requestId=<REQUEST_ID> at <TIMESTAMP>"


def test_synthetic_correlation_corpus_pairwise_precision_and_recall() -> None:
    true_positive = false_positive = false_negative = true_negative = 0

    for (
        _label,
        left_severity,
        left_message,
        right_severity,
        right_message,
        expected_same,
    ) in CORRELATION_CORPUS:
        predicted_same = _correlation_key(left_severity, left_message) == _correlation_key(
            right_severity, right_message
        )
        if expected_same and predicted_same:
            true_positive += 1
        elif not expected_same and predicted_same:
            false_positive += 1
        elif expected_same:
            false_negative += 1
        else:
            true_negative += 1

    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)
    assert (true_positive, false_positive, false_negative, true_negative) == (9, 0, 0, 8)
    assert precision == recall == 1.0


def test_analytics_groups_ipv6_and_request_ids_without_losing_source_entries(client: TestClient) -> None:
    first_message = "Connect to [2001:db8::1] failed requestId=req-abc12345 status 500"
    first_raw_line = f"2026-10-11 10:00:01 ERROR {first_message}"
    contents = (
        f"{first_raw_line}\n"
        "2026-10-11 10:00:02 ERROR Connect to [2001:db8::2] failed requestId=req-xyz98765 status 500\n"
        "2026-10-11 10:00:03 WARN Connect to [2001:db8::3] failed requestId=req-mno54321 status 500\n"
        "unstructured record stays unparsed\n"
    )
    upload_id = upload(client, "ipv6-correlation.log", contents)
    upload(
        client,
        "foreign.log",
        "2026-10-11 10:00:01 ERROR Connect to [2001:db8::4] failed "
        "requestId=req-uvw54321 status 500\n",
    )

    result = client.get(f"/api/uploads/{upload_id}/analytics").json()
    pattern = result["error_patterns"][0]

    assert result["total_entries"] == 4
    assert result["parsed_entries"] == 3
    assert result["unparsed_entries"] == 1
    assert result["error_count"] == 2
    assert result["warning_count"] == 1
    assert result["unique_error_patterns"] == 1
    assert result["recurring_error_patterns"] == 1
    assert pattern["occurrences"] == 2
    assert pattern["distinct_message_count"] == 2
    assert pattern["normalized_message_template"] == (
        "Connect to [<IP_ADDRESS>] failed requestId=<REQUEST_ID> status 500"
    )
    assert pattern["representative_message"] == first_message
    assert pattern["representative_line_numbers"] == [1, 2]
    assert pattern["first_timestamp"] == "2026-10-11T10:00:01"
    assert pattern["last_timestamp"] == "2026-10-11T10:00:02"

    entries = client.get(f"/api/uploads/{upload_id}/entries?page_size=10").json()["items"]
    assert entries[0]["message"] == pattern["representative_message"]
    assert entries[0]["raw_line"] == first_raw_line
    assert entries[3]["line_number"] == 4
    assert entries[3]["parsed"] is False
    assert entries[3]["message"] == entries[3]["raw_line"] == "unstructured record stays unparsed"

    repeated = upload(client, "same-errors.log", contents.split("\nunstructured record")[0] + "\n")
    repeated_pattern = client.get(f"/api/uploads/{repeated}/analytics").json()["error_patterns"][0]
    assert repeated_pattern["fingerprint"] == pattern["fingerprint"]
    assert "Connect to [2001:db8::4]" not in pattern["representative_message"]


def test_analytics_for_empty_dataset_preserves_response_shape(client: TestClient) -> None:
    with client.app.state.session_factory() as db:
        dataset = UploadedDataset(
            filename="empty.log",
            uploaded_at=datetime(2026, 10, 11),
            file_size_bytes=0,
            total_entries=0,
            parsed_entries=0,
            unparsed_entries=0,
        )
        db.add(dataset)
        db.commit()
        dataset_id = dataset.id

    result = client.get(f"/api/uploads/{dataset_id}/analytics").json()

    assert result["total_entries"] == result["parsed_entries"] == result["unparsed_entries"] == 0
    assert result["error_count"] == result["warning_count"] == 0
    assert result["error_patterns"] == []
    assert result["timeline"] == {"bucket_unit": "none", "bucket_interval": 1, "buckets": []}


def test_semantic_probes_are_not_claimed_as_identical_templates() -> None:
    # A/B and A/E may deserve a future semantic review, but are not exact normalized templates.
    probes = {
        "A": "Connection to host timed out",
        "B": "The remote endpoint did not respond",
        "C": "Authentication failed: invalid credentials",
        "D": "HTTP 500 Internal Server Error",
        "E": "Database connection timeout",
    }

    assert _correlation_key("ERROR", probes["A"]) != _correlation_key("ERROR", probes["B"])
    assert _correlation_key("ERROR", probes["A"]) != _correlation_key("ERROR", probes["E"])
    assert _correlation_key("ERROR", probes["C"]) != _correlation_key("ERROR", probes["D"])
    assert _correlation_key("ERROR", probes["D"]) != _correlation_key("ERROR", probes["E"])


def test_analytics_summarizes_only_selected_dataset(client: TestClient) -> None:
    selected = upload(
        client,
        "selected.log",
        "2026-10-11 10:00:01 ERROR Request failed at 192.168.0.1 status 401\n"
        "2026-10-11 10:00:02 ERROR Request failed at 10.0.0.2 status 401\n"
        "2026-10-11 10:00:03 ERROR Request failed at 10.0.0.2 status 500\n"
        "2026-10-11 10:00:04 WARN Retry scheduled\n"
        "unstructured text retained\n",
    )
    upload(client, "other.log", "2026-10-11 10:00:01 ERROR Foreign dataset error\n")

    response = client.get(f"/api/uploads/{selected}/analytics")

    assert response.status_code == 200
    result = response.json()
    assert result["total_entries"] == 5
    assert result["parsed_entries"] == 4
    assert result["unparsed_entries"] == 1
    assert result["error_count"] == 3
    assert result["warning_count"] == 1
    assert result["unique_error_patterns"] == 2
    assert result["recurring_error_patterns"] == 1
    assert result["severity_counts"]["ERROR"] == 3
    assert result["severity_counts"]["WARN"] == 1
    assert len(result["error_patterns"]) == 2
    recurring = next(pattern for pattern in result["error_patterns"] if pattern["recurring"])
    assert recurring["occurrences"] == 2
    assert recurring["representative_line_numbers"] == [1, 2]
    assert recurring["distinct_message_count"] == 2
    assert recurring["normalized_message_template"] == "Request failed at <IP_ADDRESS> status 401"
    assert all("Foreign dataset" not in pattern["representative_message"] for pattern in result["error_patterns"])
    assert result["timeline"]["bucket_unit"] == "minute"
    assert sum(bucket["entries"] for bucket in result["timeline"]["buckets"]) == 4
    assert result["timeline"]["buckets"] == [
        {
            "timestamp": "2026-10-11T10:00:00",
            "entries": 4,
            "error_count": 3,
            "warning_count": 1,
            "severity_counts": {"ERROR": 3, "WARN": 1},
        },
    ]


def test_analytics_has_empty_timeline_without_parsed_timestamps(client: TestClient) -> None:
    upload_id = upload(client, "unparsed.txt", "not a timestamped entry\n")

    result = client.get(f"/api/uploads/{upload_id}/analytics").json()

    assert result["unparsed_entries"] == 1
    assert result["parsed_entries"] == 0
    assert result["timeline"] == {"bucket_unit": "none", "bucket_interval": 1, "buckets": []}
    assert result["error_patterns"] == []


def test_error_patterns_are_bounded_and_deterministically_ranked(client: TestClient) -> None:
    content = "\n".join(
        f"2026-10-11 10:00:{second:02d} ERROR Distinct error {second}"
        for second in range(15)
    )
    upload_id = upload(client, "many.log", content)

    result = client.get(f"/api/uploads/{upload_id}/analytics").json()

    assert len(result["error_patterns"]) == MAX_ERROR_PATTERNS
    assert result["unique_error_patterns"] == 15
    assert [item["representative_message"] for item in result["error_patterns"]] == sorted(
        item["representative_message"] for item in result["error_patterns"]
    )
    assert all(item["occurrences"] == 1 and not item["recurring"] for item in result["error_patterns"])


def test_timeline_automatically_uses_wider_bounded_buckets(client: TestClient) -> None:
    upload_id = upload(
        client,
        "long-range.log",
        "1900-01-01 00:00:00 INFO Old event\n"
        "2026-10-11 10:00:00 INFO Recent event\n",
    )

    timeline = client.get(f"/api/uploads/{upload_id}/analytics").json()["timeline"]

    assert timeline["bucket_unit"] == "week"
    assert timeline["bucket_interval"] > 1
    assert len(timeline["buckets"]) <= 100
    assert sum(bucket["entries"] for bucket in timeline["buckets"]) == 2
    assert sum(bucket["error_count"] for bucket in timeline["buckets"]) == 0
    assert sum(bucket["warning_count"] for bucket in timeline["buckets"]) == 0


def test_analytics_rejects_invalid_or_missing_dataset(client: TestClient) -> None:
    invalid = client.get("/api/uploads/not-a-uuid/analytics")
    missing = client.get("/api/uploads/00000000-0000-0000-0000-000000000001/analytics")

    assert invalid.status_code == 422
    assert missing.status_code == 404
