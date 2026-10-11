from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.app.analytics import MAX_ERROR_PATTERNS, normalize_error_message
from backend.app.main import create_app


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
    assert all("Foreign dataset" not in pattern["representative_message"] for pattern in result["error_patterns"])
    assert result["timeline"]["bucket_unit"] == "minute"
    assert sum(bucket["entries"] for bucket in result["timeline"]["buckets"]) == 4


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


def test_analytics_rejects_invalid_or_missing_dataset(client: TestClient) -> None:
    invalid = client.get("/api/uploads/not-a-uuid/analytics")
    missing = client.get("/api/uploads/00000000-0000-0000-0000-000000000001/analytics")

    assert invalid.status_code == 422
    assert missing.status_code == 404
