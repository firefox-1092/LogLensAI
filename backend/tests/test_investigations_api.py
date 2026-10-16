import json
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.app.llm import LLMCompletion
from backend.app.main import create_app

SAMPLE = b"""2026-10-11 10:00:01 INFO Application started
2026-10-11 10:00:05 INFO Database connected
2026-10-11 10:01:12 ERROR Database connection timeout
2026-10-11 10:01:15 WARN Retrying database connection
Older unstructured message retained
2026-10-11 10:01:18 INFO Database connected
"""


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOG_LENS_MAX_UPLOAD_BYTES", "50000")
    app = create_app("sqlite://")
    with TestClient(app) as test_client:
        yield test_client


def make_workflow(line: int = 3) -> str:
    return json.dumps({
        "title": "Investigate database timeouts",
        "summary": "The selected dataset records a database timeout.",
        "nodes": [
            {"id": "observed", "kind": "observed_error", "status": "observed", "title": "Timeout recorded", "description": "The log records a database connection timeout.", "evidence_lines": [line]},
            {"id": "check", "kind": "investigation_step", "status": "suggested", "title": "Check pool saturation", "description": "Compare active connections with the configured pool limit.", "evidence_lines": []},
        ],
        "edges": [{"source": "observed", "target": "check", "label": "investigate"}],
        "verification_steps": ["Compare with database pool metrics."],
        "limitations": ["The logs do not establish the cause."],
    })


def upload(client: TestClient, filename: str = "sample.log") -> str:
    response = client.post("/api/uploads", files={"file": (filename, SAMPLE, "text/plain")})
    assert response.status_code == 201
    return response.json()["id"]


def pattern_fingerprint(client: TestClient, dataset_id: str) -> str:
    analytics = client.get(f"/api/uploads/{dataset_id}/analytics").json()
    return analytics["error_patterns"][0]["fingerprint"]


def test_workflow_validates_and_returns_only_real_dataset_evidence(client, monkeypatch):
    dataset_id = upload(client)
    captured = {}
    def fake_completion(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return LLMCompletion(make_workflow(), "stop", "complete")
    monkeypatch.setattr("backend.app.investigations.complete_chat", fake_completion)

    result = client.post(f"/api/uploads/{dataset_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id)})

    assert result.status_code == 200
    body = result.json()
    assert body["nodes"][0]["status"] == "observed"
    assert body["nodes"][1]["status"] == "suggested"
    assert body["evidence"][0]["line_number"] == 3
    entries = client.get(f"/api/uploads/{dataset_id}/entries").json()["items"]
    assert body["evidence"][0]["id"] in {entry["id"] for entry in entries}
    assert all(line in {entry["line_number"] for entry in entries} for node in body["nodes"] for line in node["evidence_lines"])
    assert "at most 5 nodes" in captured["messages"][0]["content"]
    payload = json.loads(captured["messages"][1]["content"])
    assert payload["allowed_evidence_line_numbers"] == [2, 3, 4]
    assert payload["allowed_source_references"] == []
    assert len(captured["messages"][1]["content"]) < 9000
    assert captured["kwargs"]["max_output_tokens"] == 2500


def test_workflow_rejects_citations_not_in_retrieved_evidence(client, monkeypatch):
    dataset_id = upload(client)
    calls = []
    monkeypatch.setattr("backend.app.investigations.complete_chat", lambda messages, **kwargs: (calls.append(messages) or LLMCompletion(make_workflow(999), "stop", "complete")))
    response = client.post(f"/api/uploads/{dataset_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id)})
    assert response.status_code == 502
    assert "valid evidence citations" in response.json()["detail"]
    assert len(calls) == 2
    assert "allowed set: [2, 3, 4]" in calls[1][-1]["content"]


def test_invalid_citation_gets_one_correction_attempt_that_can_succeed(client, monkeypatch):
    dataset_id = upload(client)
    calls = []
    responses = [
        LLMCompletion(make_workflow(999), "stop", "complete"),
        LLMCompletion(make_workflow(), "stop", "complete"),
    ]

    def fake_completion(messages, **kwargs):
        calls.append(messages)
        return responses.pop(0)

    monkeypatch.setattr("backend.app.investigations.complete_chat", fake_completion)
    response = client.post(
        f"/api/uploads/{dataset_id}/ai/investigations",
        json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id)},
    )

    assert response.status_code == 200
    assert len(calls) == 2
    assert "Rejected line identifiers [999]" in calls[1][-1]["content"]
    assert response.json()["nodes"][0]["evidence_lines"] == [3]


@pytest.mark.parametrize("edges", [
    [{"source": "observed", "target": "missing", "label": "bad"}],
    [{"source": "observed", "target": "check", "label": "a"}, {"source": "check", "target": "observed", "label": "cycle"}],
])
def test_workflow_rejects_dangling_edges_and_cycles(client, monkeypatch, edges):
    dataset_id = upload(client)
    payload = json.loads(make_workflow())
    payload["edges"] = edges
    monkeypatch.setattr("backend.app.investigations.complete_chat", lambda _messages, **kwargs: LLMCompletion(json.dumps(payload), "stop", "complete"))
    response = client.post(f"/api/uploads/{dataset_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id)})
    assert response.status_code == 502


def test_workflow_rejects_malformed_provider_output_without_logging_content(client, monkeypatch, caplog):
    dataset_id = upload(client)
    monkeypatch.setattr("backend.app.investigations.complete_chat", lambda _messages, **kwargs: LLMCompletion("not json", "stop", "complete"))
    response = client.post(f"/api/uploads/{dataset_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id)})
    assert response.status_code == 502
    assert "reason=malformed_json" in caplog.text
    assert "not json" not in caplog.text


def test_workflow_pattern_is_scoped_to_selected_dataset(client):
    first_id = upload(client, "first.log")
    client.post("/api/uploads", files={"file": ("second.log", b"2026-10-11 10:00:00 ERROR Cache lookup failed\n", "text/plain")})
    second_id = client.get("/api/uploads").json()[0]["id"]
    response = client.post(f"/api/uploads/{second_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, first_id)})
    assert response.status_code == 404


def test_workflow_handles_provider_failure_safely(client, monkeypatch):
    from backend.app.llm import LLMRateLimitError
    dataset_id = upload(client)
    monkeypatch.setattr("backend.app.investigations.complete_chat", lambda _messages, **kwargs: (_ for _ in ()).throw(LLMRateLimitError()))
    response = client.post(f"/api/uploads/{dataset_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id)})
    assert response.status_code == 429
    assert response.json()["detail"] == "The AI provider is busy. Try again shortly."


def test_source_aware_workflow_only_sends_and_returns_referenced_chunks(client, monkeypatch):
    dataset_id = upload(client)
    source_code = "def database_connection_timeout():\n    return 'database connection timeout'\n"
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("src/database.py", source_code)
    uploaded = client.put(f"/api/uploads/{dataset_id}/source-context", files={"file": ("source.zip", archive_buffer.getvalue(), "application/zip")})
    assert uploaded.status_code == 200
    payload = json.loads(make_workflow())
    payload["nodes"][0]["source_refs"] = ["S1"]
    captured = {}
    def fake_completion(messages, **kwargs):
        captured["request"] = json.loads(messages[1]["content"])
        return LLMCompletion(json.dumps(payload), "stop", "complete")
    monkeypatch.setattr("backend.app.investigations.complete_chat", fake_completion)

    result = client.post(f"/api/uploads/{dataset_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id), "include_source_context": True})

    assert result.status_code == 200
    body = result.json()
    assert body["source_context_used"] is True
    assert body["source_evidence"][0]["file_path"] == "src/database.py"
    assert body["source_evidence"][0]["content"] == source_code.strip()
    assert captured["request"]["source_context"][0]["reference"] == "S1"
    assert captured["request"]["source_context"][0]["content"] == source_code.strip()
    assert captured["request"]["allowed_source_references"] == ["S1"]


def test_source_context_is_not_sent_without_explicit_opt_in(client, monkeypatch):
    dataset_id = upload(client)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("src/database.py", "database connection internals")
    client.put(f"/api/uploads/{dataset_id}/source-context", files={"file": ("source.zip", archive_buffer.getvalue(), "application/zip")})
    captured = {}
    monkeypatch.setattr("backend.app.investigations.complete_chat", lambda messages, **kwargs: (captured.update(request=json.loads(messages[1]["content"])) or LLMCompletion(make_workflow(), "stop", "complete")))
    response = client.post(f"/api/uploads/{dataset_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id)})
    assert response.status_code == 200
    assert captured["request"]["source_context"] == []
    assert response.json()["source_context_used"] is False


def test_workflow_rejects_fabricated_source_reference(client, monkeypatch):
    dataset_id = upload(client)
    payload = json.loads(make_workflow())
    payload["nodes"][0]["source_refs"] = ["S99"]
    monkeypatch.setattr("backend.app.investigations.complete_chat", lambda _messages, **kwargs: LLMCompletion(json.dumps(payload), "stop", "complete"))
    response = client.post(f"/api/uploads/{dataset_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id)})
    assert response.status_code == 502


def test_source_aware_workflow_does_not_invent_snippets_when_none_match(client, monkeypatch):
    dataset_id = upload(client)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("src/unrelated.py", "def parse_widget(blob):\n    return blob.strip()\n")
    client.put(f"/api/uploads/{dataset_id}/source-context", files={"file": ("source.zip", archive_buffer.getvalue(), "application/zip")})

    def provider_must_not_be_called(_messages, **kwargs):
        pytest.fail("No model call should happen without relevant source snippets.")

    monkeypatch.setattr("backend.app.investigations.complete_chat", provider_must_not_be_called)
    response = client.post(
        f"/api/uploads/{dataset_id}/ai/investigations",
        json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id), "include_source_context": True},
    )

    assert response.status_code == 409
    assert "No relevant source context" in response.json()["detail"]


@pytest.mark.parametrize(("error_type", "status"), [
    ("LLMConfigurationError", 503), ("LLMTimeoutError", 504), ("LLMProviderError", 502),
])
def test_workflow_provider_failures_are_safe(client, monkeypatch, error_type, status):
    from backend.app import llm
    dataset_id = upload(client)
    exception = getattr(llm, error_type)("secret provider diagnostic")
    monkeypatch.setattr("backend.app.investigations.complete_chat", lambda _messages, **kwargs: (_ for _ in ()).throw(exception))
    response = client.post(f"/api/uploads/{dataset_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id)})
    assert response.status_code == status
    assert "secret" not in response.json()["detail"]


def test_unavailable_model_returns_actionable_but_safe_error(client, monkeypatch):
    from backend.app.llm import LLMProviderError
    dataset_id = upload(client)
    monkeypatch.setattr("backend.app.investigations.complete_chat", lambda _messages, **kwargs: (_ for _ in ()).throw(LLMProviderError("model_unavailable", 404)))
    response = client.post(f"/api/uploads/{dataset_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id)})
    assert response.status_code == 502
    assert "model is currently unavailable" in response.json()["detail"]


def test_truncated_workflow_retries_once_and_accepts_valid_json(client, monkeypatch):
    dataset_id = upload(client)
    calls = []
    responses = [
        LLMCompletion('{"nodes":[', "length", "incomplete", completion_tokens=2000),
        LLMCompletion(make_workflow(), "stop", "complete"),
    ]
    def fake_completion(messages, **kwargs):
        calls.append((messages, kwargs))
        return responses.pop(0)
    monkeypatch.setattr("backend.app.investigations.complete_chat", fake_completion)
    response = client.post(f"/api/uploads/{dataset_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id)})
    assert response.status_code == 200
    assert len(calls) == 2
    assert "previous generation was truncated" in calls[1][0][-1]["content"]
    assert calls[1][1]["max_output_tokens"] == 2500
    assert response.json()["evidence"][0]["line_number"] == 3


def test_second_truncated_workflow_returns_controlled_error(client, monkeypatch):
    dataset_id = upload(client)
    calls = []
    def fake_completion(messages, **kwargs):
        calls.append(messages)
        return LLMCompletion('{"nodes":[', "length", "incomplete", completion_tokens=2500)
    monkeypatch.setattr("backend.app.investigations.complete_chat", fake_completion)
    response = client.post(f"/api/uploads/{dataset_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id)})
    assert response.status_code == 502
    assert "after one concise retry" in response.json()["detail"]
    assert len(calls) == 2


def test_large_dataset_investigation_context_is_bounded_and_keeps_pattern_lines(client, monkeypatch):
    contents = "\n".join(
        f"2026-10-11 10:00:{second:02d} ERROR Repeated checkout failure requestId=req-{second:06d}"
        for second in range(1, 31)
    )
    dataset_id = client.post(
        "/api/uploads", files={"file": ("large.log", contents.encode(), "text/plain")}
    ).json()["id"]
    captured = {}
    def fake_completion(messages, **kwargs):
        captured["payload"] = json.loads(messages[1]["content"])
        return LLMCompletion(make_workflow(1), "stop", "complete")
    monkeypatch.setattr("backend.app.investigations.complete_chat", fake_completion)

    response = client.post(f"/api/uploads/{dataset_id}/ai/investigations", json={"pattern_fingerprint": pattern_fingerprint(client, dataset_id)})

    assert response.status_code == 200
    evidence = captured["payload"]["evidence"]
    allowed = captured["payload"]["allowed_evidence_line_numbers"]
    assert len(evidence) <= 12
    assert len(allowed) == len(evidence)
    assert set(captured["payload"]["target_pattern"]["matching_pattern_lines"]).issubset(allowed)
    assert all(1 <= line <= 30 for line in allowed)
