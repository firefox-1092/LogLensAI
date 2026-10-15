import io
import random
import string
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.source_context import index_source_archive, retrieve_source_chunks


def zip_bytes(files: dict[str, str], *, compression=zipfile.ZIP_STORED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    return buffer.getvalue()


def test_source_archive_excludes_sensitive_paths_and_redacts_secrets():
    indexed = index_source_archive(__import__("uuid").uuid4(), zip_bytes({
        "src/db.py": 'def connect_database():\n    api_key = "sk-abcdefghijklmnopqrstuvwxyz123456"\n    API_KEY = "secret value with spaces"\n    AWS_SECRET_ACCESS_KEY = "also-secret-value"\n    return "database connection"\n',
        ".env": "API_KEY=top-secret-value",
        "node_modules/lib/index.py": "irrelevant",
        "src/package.lock": "ignored",
    }))
    assert {row.file_path for row in indexed} == {"src/db.py"}
    content = "\n".join(row.content for row in indexed)
    assert "top-secret-value" not in content
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in content
    assert "secret value with spaces" not in content
    assert "also-secret-value" not in content
    assert "[REDACTED]" in content


def test_source_archive_rejects_traversal_and_symlinks():
    with pytest.raises(ValueError, match="unsafe"):
        index_source_archive(__import__("uuid").uuid4(), zip_bytes({"../outside.py": "print(1)"}))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        link = zipfile.ZipInfo("src/link.py")
        link.create_system = 3
        link.external_attr = (0o120777 << 16)
        archive.writestr(link, "target.py")
    with pytest.raises(ValueError, match="symbolic links"):
        index_source_archive(__import__("uuid").uuid4(), buffer.getvalue())


def test_source_archive_enforces_file_limit_and_rejects_invalid_zip():
    with pytest.raises(ValueError, match="256 KiB"):
        index_source_archive(__import__("uuid").uuid4(), zip_bytes({"main.py": "x" * (256 * 1024 + 1)}))
    with pytest.raises(ValueError, match="valid ZIP"):
        index_source_archive(__import__("uuid").uuid4(), b"not a zip")


def test_source_archive_enforces_member_and_total_extracted_limits():
    too_many_files = {f"src/file_{index}.py": "x" for index in range(201)}
    with pytest.raises(ValueError, match="source files"):
        index_source_archive(__import__("uuid").uuid4(), zip_bytes(too_many_files))
    seed = random.Random(4)
    repeated = "".join(seed.choices(string.ascii_letters + string.digits, k=20_000))
    large_text = (repeated * (250 * 1024 // len(repeated) + 1))[:250 * 1024]
    large_files = {f"src/file_{index}.py": large_text for index in range(62)}
    with pytest.raises(ValueError, match="15 MiB"):
        index_source_archive(__import__("uuid").uuid4(), zip_bytes(large_files, compression=zipfile.ZIP_DEFLATED))


@pytest.fixture
def client():
    app = create_app("sqlite://")
    with TestClient(app) as test_client:
        yield test_client


def create_dataset(client: TestClient) -> str:
    response = client.post("/api/uploads", files={"file": ("tiny.log", b"2026-10-11 10:00:00 INFO Started\n", "text/plain")})
    assert response.status_code == 201
    return response.json()["id"]


def test_source_context_replace_status_delete_and_dataset_isolation(client: TestClient):
    one = create_dataset(client)
    two = create_dataset(client)
    archive = zip_bytes({"src/database.py": "def connect_database():\n    return 'database connection'\n"})
    response = client.put(f"/api/uploads/{one}/source-context", files={"file": ("code.zip", archive, "application/zip")})
    assert response.status_code == 200
    assert response.json()["files"] == 1
    assert client.get(f"/api/uploads/{one}/source-context").json()["chunks"] >= 1
    assert client.get(f"/api/uploads/{two}/source-context").json() == {"files": 0, "chunks": 0}

    delete = client.delete(f"/api/uploads/{one}/source-context")
    assert delete.status_code == 204
    assert client.get(f"/api/uploads/{one}/source-context").json() == {"files": 0, "chunks": 0}


def test_source_context_upload_rejects_bad_filename_or_archive(client: TestClient):
    dataset_id = create_dataset(client)
    wrong = client.put(f"/api/uploads/{dataset_id}/source-context", files={"file": ("source.tar", b"bad", "application/octet-stream")})
    bad_zip = client.put(f"/api/uploads/{dataset_id}/source-context", files={"file": ("source.zip", b"bad", "application/zip")})
    assert wrong.status_code == 400
    assert bad_zip.status_code == 400


def test_source_upload_enforces_compressed_byte_limit(client: TestClient):
    dataset_id = create_dataset(client)
    oversized = client.put(
        f"/api/uploads/{dataset_id}/source-context",
        files={"file": ("source.zip", b"x" * (5 * 1024 * 1024 + 1), "application/zip")},
    )
    assert oversized.status_code == 413


def test_source_retrieval_never_crosses_dataset(client: TestClient):
    one = create_dataset(client)
    two = create_dataset(client)
    source = index_source_archive(__import__("uuid").UUID(one), zip_bytes({"src/database.py": "database connection pool"}))
    app = client.app
    with app.state.session_factory() as db:
        db.add_all(source); db.commit()
        assert retrieve_source_chunks(db, __import__("uuid").UUID(one), "database connection")
        assert retrieve_source_chunks(db, __import__("uuid").UUID(two), "database connection") == []
