from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.app.database import get_db
from backend.app.main import create_app

SAMPLE_LOG = b"""2026-10-11 10:00:01 INFO Application started
2026-10-11 10:00:05 INFO Database connected
2026-10-11 10:01:12 ERROR Database connection timeout
2026-10-11 10:01:15 WARNING Retrying database connection
malformed event from an older service
"""


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("LOG_LENS_MAX_UPLOAD_BYTES", "1024")
    app = create_app("sqlite://")
    with TestClient(app) as test_client:
        yield test_client


def test_upload_persists_dataset_and_entries(client: TestClient) -> None:
    response = client.post(
        "/api/uploads",
        files={"file": ("sample.log", SAMPLE_LOG, "text/plain")},
    )

    assert response.status_code == 201
    uploaded = response.json()
    assert uploaded["filename"] == "sample.log"
    assert uploaded["total_entries"] == 5
    assert uploaded["parsed_entries"] == 4
    assert uploaded["unparsed_entries"] == 1
    assert uploaded["file_size_bytes"] == len(SAMPLE_LOG)

    listed = client.get("/api/uploads")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == uploaded["id"]

    entries = client.get(f"/api/uploads/{uploaded['id']}/entries")
    assert entries.status_code == 200
    assert entries.json()["total"] == 5
    first_entry = entries.json()["items"][0]
    assert first_entry["timestamp"] == "2026-10-11T10:00:01"
    assert first_entry["severity"] == "INFO"
    assert first_entry["message"] == "Application started"
    assert first_entry["raw_line"] == "2026-10-11 10:00:01 INFO Application started"
    assert first_entry["line_number"] == 1
    assert first_entry["parsed"] is True
    assert entries.json()["items"][4]["message"] == "malformed event from an older service"
    assert entries.json()["items"][4]["raw_line"] == "malformed event from an older service"
    assert entries.json()["items"][4]["parsed"] is False


def test_entry_pagination_severity_and_keyword_filters(client: TestClient) -> None:
    uploaded = client.post(
        "/api/uploads", files={"file": ("sample.txt", SAMPLE_LOG, "text/plain")}
    ).json()
    upload_id = uploaded["id"]

    first_page = client.get(f"/api/uploads/{upload_id}/entries?page=1&page_size=2")
    assert first_page.json()["page"] == 1
    assert first_page.json()["page_size"] == 2
    assert first_page.json()["total"] == 5
    assert first_page.json()["total_pages"] == 3
    assert len(first_page.json()["items"]) == 2

    warning_entries = client.get(
        f"/api/uploads/{upload_id}/entries?severity=WARNING"
    ).json()
    assert warning_entries["total"] == 1
    assert warning_entries["items"][0]["severity"] == "WARN"

    matches = client.get(
        f"/api/uploads/{upload_id}/entries?q=DATABASE%20CONNECTION"
    ).json()
    assert matches["total"] == 2

    source_line = client.get(f"/api/uploads/{upload_id}/entries?line_number=3")
    assert source_line.json()["total"] == 1
    assert source_line.json()["items"][0]["line_number"] == 3


@pytest.mark.parametrize(
    ("filename", "content", "limit", "expected_status"),
    [
        ("empty.log", b"", "1024", 400),
        ("wrong.csv", b"some text", "1024", 400),
        ("invalid.log", b"\xff\xfe", "1024", 400),
        ("too-large.log", b"x" * 20, "10", 413),
        ("blank.txt", b" \n\t\n", "1024", 400),
    ],
)
def test_invalid_uploads_are_rejected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    content: bytes,
    limit: str,
    expected_status: int,
) -> None:
    monkeypatch.setenv("LOG_LENS_MAX_UPLOAD_BYTES", limit)

    response = client.post(
        "/api/uploads", files={"file": (filename, content, "text/plain")}
    )

    assert response.status_code == expected_status
    assert "detail" in response.json()


def test_missing_upload_returns_404(client: TestClient) -> None:
    response = client.get(
        "/api/uploads/00000000-0000-0000-0000-000000000001/entries"
    )

    assert response.status_code == 404


def test_invalid_upload_id_returns_422(client: TestClient) -> None:
    response = client.get("/api/uploads/not-a-uuid/entries")

    assert response.status_code == 422


def test_invalid_filter_and_pagination_are_rejected(client: TestClient) -> None:
    upload_id = client.post(
        "/api/uploads", files={"file": ("sample.log", SAMPLE_LOG, "text/plain")}
    ).json()["id"]

    invalid_severity = client.get(f"/api/uploads/{upload_id}/entries?severity=UNKNOWN")
    invalid_page = client.get(f"/api/uploads/{upload_id}/entries?page=0")

    assert invalid_severity.status_code == 422
    assert invalid_page.status_code == 422


def test_database_errors_do_not_expose_sql_details() -> None:
    app = create_app("sqlite://")

    def broken_database():
        raise OperationalError("select private_data", {}, Exception("sensitive driver detail"))

    app.dependency_overrides[get_db] = broken_database
    with TestClient(app) as client:
        response = client.get("/api/uploads")

    assert response.status_code == 503
    assert "select private_data" not in response.text
    assert "sensitive driver detail" not in response.text
