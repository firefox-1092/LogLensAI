from types import ModuleType, SimpleNamespace
import sys

import pytest

from backend.app.llm import (
    LLMConfigurationError,
    LLMProviderError,
    LLMRateLimitError,
    _normalize_completion,
    complete_chat,
    get_configuration,
)


def test_groq_is_default_and_reads_its_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "private-groq-test-key")
    monkeypatch.setenv("GROQ_MODEL", "configured/groq-model")

    configuration = get_configuration()

    assert configuration.provider == "groq"
    assert configuration.model == "configured/groq-model"
    assert configuration.api_key == "private-groq-test-key"


def test_openrouter_selection_requires_its_key_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-openrouter-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "user/configured-model")

    configuration = get_configuration()

    assert configuration.provider == "openrouter"
    assert configuration.model == "user/configured-model"
    assert configuration.api_key == "private-openrouter-test-key"

    monkeypatch.delenv("OPENROUTER_MODEL")
    with pytest.raises(LLMConfigurationError, match="OPENROUTER_MODEL"):
        get_configuration()


def test_invalid_provider_and_missing_credentials_fail_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    with pytest.raises(LLMConfigurationError, match="LLM_PROVIDER"):
        get_configuration()

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError, match="Credentials"):
        get_configuration()


@pytest.mark.parametrize(
    ("reason", "status"),
    [("stop", "complete"), ("length", "incomplete"), (None, "unknown")],
)
def test_normalizes_provider_finish_reasons(reason: str | None, status: str) -> None:
    response = {
        "choices": [{"finish_reason": reason, "message": {"content": "Answer."}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
    }

    completion = _normalize_completion(response)

    assert completion.completion_status == status
    assert completion.prompt_tokens == 11
    assert completion.completion_tokens == 5
    assert completion.total_tokens == 16


def test_groq_call_uses_selected_model_and_logs_no_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    captured: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="A complete answer."))],
                usage=SimpleNamespace(prompt_tokens=12, completion_tokens=6, total_tokens=18),
            )

    class FakeGroq:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "private-test-key"
            self.chat = SimpleNamespace(completions=FakeCompletions())

    fake_sdk = ModuleType("groq")
    for name in ("APIConnectionError", "APITimeoutError", "APIStatusError", "RateLimitError"):
        setattr(fake_sdk, name, type(name, (Exception,), {}))
    fake_sdk.Groq = FakeGroq
    monkeypatch.setitem(sys.modules, "groq", fake_sdk)
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "private-test-key")
    monkeypatch.setenv("GROQ_MODEL", "selected/groq-model")

    result = complete_chat([{"role": "user", "content": "Question"}])

    assert captured["model"] == "selected/groq-model"
    assert result.content == "A complete answer."
    assert result.completion_status == "complete"
    assert "provider=groq" in caplog.text
    assert "model=selected/groq-model" in caplog.text
    assert "private-test-key" not in caplog.text


def test_openrouter_call_uses_official_endpoint_and_selected_model(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    captured: dict[str, object] = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "choices": [{"finish_reason": "stop", "message": {"content": "Router answer."}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-openrouter-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "selected/router-model")

    result = complete_chat([{"role": "user", "content": "Question"}])

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer private-openrouter-test-key"
    assert captured["json"]["model"] == "selected/router-model"
    assert result.content == "Router answer."


def test_openrouter_rate_limit_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: SimpleNamespace(status_code=429))
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "selected/router-model")

    with pytest.raises(LLMRateLimitError):
        complete_chat([{"role": "user", "content": "Question"}])


@pytest.mark.parametrize(
    ("status_code", "error"),
    [(401, LLMConfigurationError), (503, LLMProviderError)],
)
def test_openrouter_provider_errors_are_safe(
    monkeypatch: pytest.MonkeyPatch, status_code: int, error: type[Exception]
) -> None:
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: SimpleNamespace(status_code=status_code))
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "selected/router-model")

    with pytest.raises(error):
        complete_chat([{"role": "user", "content": "Question"}])
