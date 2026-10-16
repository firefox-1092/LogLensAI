"""Provider-neutral chat completion configuration and adapters."""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMConfigurationError(Exception):
    """The selected provider or its credentials are not configured."""

    def __init__(self, message: str = "configuration_error", status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class LLMProviderError(Exception):
    """Provider failure with safe, non-secret diagnostic metadata."""

    def __init__(self, diagnostic: str = "provider_error", status_code: int | None = None):
        super().__init__(diagnostic)
        self.diagnostic = diagnostic
        self.status_code = status_code


class LLMRateLimitError(LLMProviderError):
    """A provider rate limit was reached."""


class LLMTimeoutError(LLMProviderError):
    """A provider request exceeded its timeout."""


@dataclass(frozen=True)
class LLMConfiguration:
    provider: str
    model: str
    api_key: str


@dataclass(frozen=True)
class LLMCompletion:
    content: str
    finish_reason: str | None
    completion_status: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


def get_configuration() -> LLMConfiguration:
    """Load provider and credentials without logging secret values."""
    provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    if provider not in {"groq", "openrouter"}:
        raise LLMConfigurationError("LLM_PROVIDER must be either 'groq' or 'openrouter'.")

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
        model = model or "openai/gpt-oss-20b"
    else:
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        model = os.getenv("OPENROUTER_MODEL", "").strip()
        if not model:
            raise LLMConfigurationError("OPENROUTER_MODEL must be set when LLM_PROVIDER=openrouter.")

    if not api_key:
        raise LLMConfigurationError(f"Credentials for the selected provider ({provider}) are missing.")
    return LLMConfiguration(provider, model, api_key)


def _usage_values(usage: Any) -> tuple[int | None, int | None, int | None]:
    if usage is None:
        return None, None, None
    if isinstance(usage, dict):
        values = (usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"))
    else:
        values = (
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
            getattr(usage, "total_tokens", None),
        )
    return tuple(value if isinstance(value, int) else None for value in values)  # type: ignore[return-value]


def _normalize_completion(payload: Any) -> LLMCompletion:
    try:
        choice = payload["choices"][0] if isinstance(payload, dict) else payload.choices[0]
        if isinstance(choice, dict):
            finish_reason = choice.get("finish_reason")
            message = choice.get("message") or {}
            content = message.get("content") if isinstance(message, dict) else None
        else:
            finish_reason = getattr(choice, "finish_reason", None)
            content = getattr(getattr(choice, "message", None), "content", None)
        usage = payload.get("usage") if isinstance(payload, dict) else getattr(payload, "usage", None)
    except (AttributeError, IndexError, KeyError, TypeError):
        raise LLMProviderError("invalid_provider_response") from None

    if not isinstance(content, str) or not content.strip():
        raise LLMProviderError("empty_provider_response")
    reason = finish_reason.strip().lower() if isinstance(finish_reason, str) else None
    if reason in {"length", "max_tokens", "max_output_tokens", "token_limit"}:
        status = "incomplete"
    elif reason in {"stop", "end_turn", "completed"}:
        status = "complete"
    elif reason is None or reason not in {"tool_calls", "content_filter", "error", "cancelled"}:
        status = "unknown"
    else:
        raise LLMProviderError("unsupported_finish_reason")
    prompt_tokens, completion_tokens, total_tokens = _usage_values(usage)
    return LLMCompletion(
        content=content.strip(),
        finish_reason=reason,
        completion_status=status,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def _groq_completion(
    configuration: LLMConfiguration,
    messages: list[dict[str, str]],
    max_output_tokens: int,
) -> Any:
    try:
        from groq import APIConnectionError, APITimeoutError, APIStatusError, Groq, RateLimitError
    except ImportError:
        raise LLMProviderError("provider_sdk_unavailable") from None

    try:
        client = Groq(api_key=configuration.api_key, timeout=25.0, max_retries=0)
        return client.chat.completions.create(
            model=configuration.model,
            messages=messages,
            max_completion_tokens=max_output_tokens,
            temperature=0.2,
        )
    except APITimeoutError:
        raise LLMTimeoutError from None
    except RateLimitError:
        raise LLMRateLimitError("upstream_rate_limited", 429) from None
    except APIStatusError as exc:
        if exc.status_code in {401, 403}:
            raise LLMConfigurationError("provider_authentication_rejected", exc.status_code) from None
        category = "model_unavailable" if exc.status_code == 404 else "upstream_unavailable" if exc.status_code == 503 else "upstream_http_error"
        raise LLMProviderError(category, exc.status_code) from None
    except APIConnectionError:
        raise LLMProviderError("provider_connection_error") from None
    except Exception:
        raise LLMProviderError("provider_request_error") from None


def _openrouter_completion(
    configuration: LLMConfiguration,
    messages: list[dict[str, str]],
    max_output_tokens: int,
) -> Any:
    try:
        import httpx
    except ImportError:
        raise LLMProviderError from None

    try:
        response = httpx.post(
            OPENROUTER_CHAT_URL,
            headers={
                "Authorization": f"Bearer {configuration.api_key}",
                "Content-Type": "application/json",
                "X-Title": "LogLens",
            },
            json={"model": configuration.model, "messages": messages, "max_tokens": max_output_tokens, "temperature": 0.2},
            timeout=25.0,
        )
    except httpx.TimeoutException:
        raise LLMTimeoutError from None
    except httpx.RequestError:
        raise LLMProviderError("provider_connection_error") from None

    if response.status_code == 429:
        raise LLMRateLimitError("upstream_rate_limited", response.status_code)
    if response.status_code in {401, 403}:
        raise LLMConfigurationError("provider_authentication_rejected", response.status_code) from None
    if response.status_code >= 400:
        category = "model_unavailable" if response.status_code == 404 else "upstream_unavailable" if response.status_code == 503 else "upstream_http_error"
        raise LLMProviderError(category, response.status_code) from None
    try:
        return response.json()
    except ValueError:
        raise LLMProviderError("invalid_provider_json") from None


def complete_chat(
    messages: list[dict[str, str]], *, max_output_tokens: int = 2000
) -> LLMCompletion:
    """Call the configured provider and normalize response metadata."""
    if not 1 <= max_output_tokens <= 4096:
        raise ValueError("max_output_tokens must be between 1 and 4096.")
    configuration = get_configuration()
    started = time.monotonic()
    try:
        raw = (
            _groq_completion(configuration, messages, max_output_tokens)
            if configuration.provider == "groq"
            else _openrouter_completion(configuration, messages, max_output_tokens)
        )
        completion = _normalize_completion(raw)
    except (LLMConfigurationError, LLMProviderError) as exc:
        logger.warning(
            "LLM request failed provider=%s model=%s error_type=%s diagnostic=%s upstream_status=%s duration_ms=%d",
            configuration.provider,
            configuration.model,
            type(exc).__name__,
            (
                "timeout" if isinstance(exc, LLMTimeoutError)
                else exc.diagnostic if isinstance(exc, LLMProviderError)
                else "configuration_error"
            ),
            exc.status_code if isinstance(exc, (LLMProviderError, LLMConfigurationError)) and exc.status_code else "unavailable",
            int((time.monotonic() - started) * 1000),
        )
        raise

    logger.info(
        "LLM response provider=%s model=%s finish_reason=%s completion_status=%s "
        "prompt_tokens=%s completion_tokens=%s total_tokens=%s duration_ms=%d",
        configuration.provider,
        configuration.model,
        completion.finish_reason or "unavailable",
        completion.completion_status,
        completion.prompt_tokens,
        completion.completion_tokens,
        completion.total_tokens,
        int((time.monotonic() - started) * 1000),
    )
    return completion
