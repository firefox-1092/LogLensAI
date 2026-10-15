from collections.abc import Iterator
import json
import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.ai import AIIncompleteResponse, _completion_answer, _request_llm_completion
from backend.app.llm import LLMCompletion


def completed(content: str, status: str = "complete") -> LLMCompletion:
    return LLMCompletion(content, "stop" if status == "complete" else None, status)

SAMPLE_LOG = b"""2026-10-11 10:00:01 INFO Application started
2026-10-11 10:00:05 INFO Database connected
2026-10-11 10:01:12 ERROR Database connection timeout
2026-10-11 10:01:15 WARNING Retrying database connection
Older unstructured message retained as an unparsed entry
2026-10-11 10:01:18 INFO Database connected
"""


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("LOG_LENS_MAX_UPLOAD_BYTES", "50000")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    app = create_app("sqlite://")
    with TestClient(app) as test_client:
        yield test_client


def upload_sample(client: TestClient) -> str:
    response = client.post(
        "/api/uploads", files={"file": ("sample.log", SAMPLE_LOG, "text/plain")}
    )
    assert response.status_code == 201
    return response.json()["id"]


def ask(
    client: TestClient,
    upload_id: str,
    question: str = "Why did the database connection fail?",
    history: list[dict[str, str]] | None = None,
):
    return client.post(
        f"/api/uploads/{upload_id}/ai/chat",
        json={"question": question, "history": history or []},
    )


def test_ai_chat_returns_answer_and_supporting_evidence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_id = upload_sample(client)
    captured: dict[str, object] = {}

    def fake_completion(question, evidence, history, scope):
        captured["question"] = question
        captured["evidence"] = evidence
        captured["history"] = history
        captured["scope"] = scope
        return completed(
            "### Observed facts\n- **Line 3** records a database connection timeout.\n\n"
            "### Possible explanations\nThe logs do not establish what caused it."
        )

    monkeypatch.setattr("backend.app.ai._request_llm_completion", fake_completion)
    response = ask(client, upload_id)

    assert response.status_code == 200
    body = response.json()
    assert "### Observed facts" in body["answer"]
    assert "**Line 3**" in body["answer"]
    assert any(item["line_number"] == 3 for item in body["evidence"])
    assert any(item["message"] == "Database connection timeout" for item in body["evidence"])
    dataset_rows = client.get(f"/api/uploads/{upload_id}/entries").json()["items"]
    rows_by_id = {row["id"]: row for row in dataset_rows}
    assert all(reference["id"] in rows_by_id for reference in body["evidence"])
    assert all(
        rows_by_id[reference["id"]]["line_number"] == reference["line_number"]
        and rows_by_id[reference["id"]]["message"] == reference["message"]
        for reference in body["evidence"]
    )
    assert all(reference["id"] in rows_by_id for reference in body["cited_evidence"])
    assert all(
        rows_by_id[reference["id"]]["line_number"] == reference["line_number"]
        for reference in body["cited_evidence"]
    )
    assert captured["question"] == "Why did the database connection fail?"
    assert len(captured["evidence"]) == 6
    assert "COMPLETE DATASET" in captured["scope"]
    assert any(item["line_number"] == 1 for item in captured["evidence"])
    assert any(item["line_number"] == 5 and item["parsed"] is False for item in captured["evidence"])


def test_follow_up_uses_prior_question_for_keyword_retrieval(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_id = upload_sample(client)
    captured: dict[str, object] = {}

    def fake_completion(_question, evidence, history, scope):
        captured["history"] = history
        captured["evidence"] = evidence
        captured["scope"] = scope
        return completed("The next relevant event is the retry at line 4.")

    monkeypatch.setattr("backend.app.ai._request_llm_completion", fake_completion)
    response = ask(
        client,
        upload_id,
        "What happened next?",
        [{"question": "Why did the database connection fail?", "answer": "It timed out."}],
    )

    assert response.status_code == 200
    assert {item["line_number"] for item in response.json()["evidence"]} >= {3, 4}
    assert captured["history"][0].question == "Why did the database connection fail?"


def test_startup_question_includes_explicit_entry_and_does_not_invent_cause(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_id = upload_sample(client)
    captured: dict[str, object] = {}

    def fake_completion(question, evidence, _history, scope):
        captured.update(question=question, evidence=evidence, scope=scope)
        startup = next(item for item in evidence if item["line_number"] == 1)
        assert startup["message"] == "Application started"
        return completed("Line 1 explicitly records that the application started. The logs do not record what caused it.")

    monkeypatch.setattr("backend.app.ai._request_llm_completion", fake_completion)
    response = ask(client, upload_id, "What caused the application to start?")

    assert response.status_code == 200
    answer = response.json()["answer"].lower()
    assert "line 1" in answer and "application started" in answer
    assert "do not record what caused" in answer
    assert "COMPLETE DATASET" in captured["scope"]
    assert [item["line_number"] for item in response.json()["evidence"]] == [1, 2, 3, 4, 5, 6]
    assert [item["line_number"] for item in response.json()["cited_evidence"]] == [1]


def test_multiple_explicit_line_citations_filter_supporting_entries(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_id = upload_sample(client)
    monkeypatch.setattr(
        "backend.app.ai._request_llm_completion",
        lambda *_args: completed("Lines 2, 4, and 6 record database events."),
    )

    response = ask(client, upload_id, "Which lines record database events?")

    assert response.status_code == 200
    assert [item["line_number"] for item in response.json()["cited_evidence"]] == [2, 4, 6]


def test_unknown_completion_status_is_visible_in_api_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_id = upload_sample(client)
    monkeypatch.setattr(
        "backend.app.ai._request_llm_completion",
        lambda *_args: LLMCompletion("A brief answer.", None, "unknown"),
    )

    response = ask(client, upload_id, "What happened?")

    assert response.status_code == 200
    assert response.json()["completion_status"] == "unknown"


def test_keyword_variants_find_started_entry_in_large_dataset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = [f"2026-10-11 10:00:{i:02d} INFO Routine activity {i}" for i in range(30)]
    records[0] = "2026-10-11 10:00:01 INFO Application started"
    log = "\n".join(records).encode()
    upload = client.post("/api/uploads", files={"file": ("large.log", log, "text/plain")})
    assert upload.status_code == 201
    upload_id = upload.json()["id"]
    captured: dict[str, object] = {}

    def fake_completion(_question, evidence, _history, scope):
        captured.update(evidence=evidence, scope=scope)
        return completed("Line 1 records application startup; its cause is not established.")

    monkeypatch.setattr("backend.app.ai._request_llm_completion", fake_completion)
    response = ask(client, upload_id, "What caused the application startup?")

    assert response.status_code == 200
    assert any(item["line_number"] == 1 for item in captured["evidence"])
    assert len(captured["evidence"]) <= 12
    assert "RETRIEVED SUBSET" in captured["scope"]


def test_relevant_unparsed_entries_are_identified_as_unparsed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_id = upload_sample(client)
    captured: dict[str, object] = {}

    def fake_completion(_question, evidence, _history, _scope):
        captured["evidence"] = evidence
        return completed("The matching entry is unparsed, so its structure is unknown.")

    monkeypatch.setattr("backend.app.ai._request_llm_completion", fake_completion)
    response = ask(client, upload_id, "older service")

    assert response.status_code == 200
    assert any(entry["parsed"] is False for entry in captured["evidence"])
    assert any(reference["parsed"] is False for reference in response.json()["evidence"])
    unparsed = next(item for item in response.json()["evidence"] if not item["parsed"])
    assert unparsed["raw_line"] == "Older unstructured message retained as an unparsed entry"
    assert unparsed["timestamp"] is None
    assert unparsed["severity"] is None


def test_missing_api_key_returns_safe_configuration_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_id = upload_sample(client)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    response = ask(client, upload_id)

    assert response.status_code == 503
    assert "selected provider's API key" in response.json()["detail"]
    assert "sk-" not in response.text


@pytest.mark.parametrize(
    ("error_name", "status_code", "detail"),
    [
        (
            "AIRateLimitError",
            429,
            "The AI provider is busy. Wait a moment and try again.",
        ),
        (
            "AITimeoutError",
            504,
            "The AI provider took too long to respond. Please try again.",
        ),
        (
            "AIProviderError",
            502,
            "The AI provider could not complete the request. Please try again later.",
        ),
    ],
)
def test_provider_failures_return_safe_statuses(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error_name: str,
    status_code: int,
    detail: str,
) -> None:
    upload_id = upload_sample(client)
    monkeypatch.setenv("GROQ_API_KEY", "test-only-secret")
    from backend.app import ai

    error_type = getattr(ai, error_name)

    def fail_completion(_question, _evidence, _history, _scope):
        raise error_type("private provider detail")

    monkeypatch.setattr(ai, "_request_llm_completion", fail_completion)
    response = ask(client, upload_id)

    assert response.status_code == status_code
    assert response.json()["detail"] == detail
    assert "private provider detail" not in response.text
    assert "test-only-secret" not in response.text


def test_incomplete_provider_response_has_clear_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_id = upload_sample(client)
    from backend.app import ai

    def incomplete_completion(_question, _evidence, _history, _scope):
        raise ai.AIIncompleteResponse

    monkeypatch.setattr(ai, "_request_llm_completion", incomplete_completion)
    response = ask(client, upload_id)

    assert response.status_code == 502
    assert "output token limit was reached" in response.json()["detail"]


def test_confirmed_length_limit_is_rejected_but_complete_markdown_is_accepted() -> None:
    complete_markdown = LLMCompletion("A valid answer ending with **", "stop", "complete")
    assert _completion_answer(complete_markdown).content == "A valid answer ending with **"

    truncated = LLMCompletion("Suggested next steps:\n1. **", "length", "incomplete")
    with pytest.raises(AIIncompleteResponse):
        _completion_answer(truncated)


def test_missing_finish_metadata_is_marked_unknown() -> None:
    result = _completion_answer(LLMCompletion("Concise answer.", None, "unknown"))
    assert result.completion_status == "unknown"


def test_provider_neutral_request_preserves_grounding_rules_and_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    answer = "### Observed facts\n- **Line 3** shows a timeout."
    def fake_complete_chat(*, messages):
        captured["messages"] = messages
        return completed(answer)

    monkeypatch.setattr("backend.app.ai.complete_chat", fake_complete_chat)
    result = _request_llm_completion(
        "What happened?",
        [{"id": "entry-id", "line_number": 3, "timestamp": "2026-10-11T10:01:12", "severity": "ERROR", "message": "Database timeout", "parsed": True}],
        [],
        "COMPLETE DATASET: all 1 entries are included without per-entry truncation.",
    )

    system_prompt = captured["messages"][0]["content"]
    assert result.content == answer
    assert "Temporal order alone does not prove causation" in system_prompt
    assert "Acknowledge relevant unparsed entries" in system_prompt
    assert "Explicitly say when logs are insufficient" in system_prompt
    assert "say an event was not present in the retrieved entries" in system_prompt
    assert "Evidence scope: COMPLETE DATASET" in captured["messages"][1]["content"]


def test_small_dataset_without_keyword_match_still_sends_complete_evidence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_id = upload_sample(client)
    captured: dict[str, object] = {}

    def fake_completion(_question, evidence, _history, scope):
        captured.update(evidence=evidence, scope=scope)
        return completed("The complete dataset does not mention a payment gateway.")

    monkeypatch.setattr("backend.app.ai._request_llm_completion", fake_completion)
    response = ask(client, upload_id, "What happened to the payment gateway?")

    assert response.status_code == 200
    assert len(captured["evidence"]) == 6
    assert "COMPLETE DATASET" in captured["scope"]
    assert len(response.json()["evidence"]) == 6


def test_invalid_dataset_and_question_are_rejected(client: TestClient) -> None:
    invalid_id = ask(client, "not-a-uuid")
    missing_id = ask(client, "00000000-0000-0000-0000-000000000001")
    blank_question = client.post(
        "/api/uploads/00000000-0000-0000-0000-000000000001/ai/chat",
        json={"question": "   "},
    )

    assert invalid_id.status_code == 422
    assert missing_id.status_code == 404
    assert blank_question.status_code == 422


def test_evidence_count_and_message_size_are_bounded(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    long_message = "Database connection failed " + ("x" * 1300)
    log = "\n".join(
        f"2026-10-11 10:00:{second:02d} ERROR {long_message}"
        for second in range(15)
    ).encode()
    upload = client.post("/api/uploads", files={"file": ("many.log", log, "text/plain")})
    assert upload.status_code == 201
    upload_id = upload.json()["id"]
    captured: dict[str, object] = {}

    def fake_completion(_q, evidence, _h, scope):
        captured.update(evidence=evidence, scope=scope)
        return completed("Found errors.")

    monkeypatch.setattr("backend.app.ai._request_llm_completion", fake_completion)

    response = ask(client, upload_id, "database connection failed")

    assert response.status_code == 200
    assert len(response.json()["evidence"]) <= 12
    assert all(len(item["message"]) <= 1200 for item in response.json()["evidence"])
    assert len(json.dumps(captured["evidence"], ensure_ascii=True)) <= 16000
    assert "RETRIEVED SUBSET" in captured["scope"]


def test_ai_retrieval_can_use_structured_json_upload(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    response = client.post(
        "/api/uploads",
        files={"file": ("structured.ndjson", b'{"@timestamp":"2026-10-11T10:00:00Z","level":"ERROR","message":"Database connection timeout"}\n', "application/x-ndjson")},
    )
    assert response.status_code == 201
    upload_id = response.json()["id"]
    captured = {}
    def fake_completion(_question, evidence, _history, _scope):
        captured["evidence"] = evidence
        return completed("Line 1 records a database connection timeout.")
    monkeypatch.setattr("backend.app.ai._request_llm_completion", fake_completion)

    result = ask(client, upload_id, "What database event was recorded?")

    assert result.status_code == 200
    assert captured["evidence"][0]["line_number"] == 1
    assert captured["evidence"][0]["message"] == "Database connection timeout"
