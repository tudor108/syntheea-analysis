"""One hardened OpenAI SDK boundary shared by all AI Studio model capabilities."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterator
from typing import Any

from .ai_studio_config import AIStudioSettings


class ProviderRequestError(RuntimeError):
    """Sanitized provider failure carrying only an allow-listed operational category."""

    def __init__(self, category: str, *, partial: bool = False) -> None:
        super().__init__(f"OpenAI provider request failed: {category}.")
        self.category = category
        self.partial = partial


def provider_failure_category(error: BaseException) -> str:
    """Recover only an allow-listed provider category through wrapped exceptions."""
    current: BaseException | None = error
    for _ in range(6):
        if current is None:
            break
        if isinstance(current, ProviderRequestError):
            return current.category
        category = getattr(current, "category", None)
        if isinstance(category, str) and category:
            return category[:80]
        current = current.__cause__ or current.__context__
    return "application_failure"


def _import_openai() -> Any:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise ProviderRequestError("sdk_unavailable") from error
    return OpenAI


def _provider_error_code(error: Exception) -> str:
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        candidate = body.get("error")
        nested = candidate if isinstance(candidate, dict) else body
        value = nested.get("code") or nested.get("type")
        if value:
            return str(value)[:80]
    return ""


def _category(error: Exception) -> str:
    code = _provider_error_code(error).casefold()
    status = int(getattr(error, "status_code", 0) or 0)
    name = type(error).__name__.casefold()
    if "credit" in code or "quota" in code:
        return "budget_or_quota_exhausted"
    if status == 429:
        return "rate_limited"
    if status in {408, 409} or status >= 500:
        return "transient_provider_error"
    if "timeout" in name:
        return "timeout"
    if "connection" in name:
        return "connection_error"
    if status in {400, 404, 422}:
        return "invalid_provider_request"
    if status in {401, 403}:
        return "provider_authentication_failed"
    return "provider_unavailable"


def _transient(error: Exception) -> bool:
    category = _category(error)
    return category in {"rate_limited", "transient_provider_error", "timeout", "connection_error"}


def iterate_response_stream(stream: Any) -> Iterator[Any]:
    """Yield provider events while converting stream failures to sanitized categories.

    A failure after a response stream has started must never be retried because the
    provider may already have completed and billed part of the request. The caller
    can fail closed while retaining an operationally useful, non-sensitive reason.
    """

    try:
        yield from stream
    except Exception as error:
        raise ProviderRequestError(_category(error), partial=True) from error


class AIProviderClient:
    """Central client with explicit retries, stable cache keys, and sanitized errors."""

    def __init__(
        self,
        settings: AIStudioSettings,
        *,
        raw_client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        retry_initial_backoff_seconds: float = 0.25,
        maximum_attempts: int = 2,
    ) -> None:
        self.settings = settings
        self._raw = raw_client
        self._sleep = sleep
        self.retry_initial_backoff_seconds = retry_initial_backoff_seconds
        self.maximum_attempts = maximum_attempts

    @property
    def configured(self) -> bool:
        return self.settings.provider_enabled and (
            self.settings.openai_api_key is not None or self._raw is not None
        )

    def raw_client(self) -> Any:
        if not self.settings.provider_enabled:
            raise ProviderRequestError("provider_disabled")
        if self._raw is not None:
            return self._raw
        if self.settings.openai_api_key is None:
            raise ProviderRequestError("api_key_not_configured")
        OpenAI = _import_openai()
        self._raw = OpenAI(
            api_key=self.settings.openai_api_key.get_secret_value(),
            timeout=self.settings.request_timeout_seconds,
            max_retries=0,
        )
        return self._raw

    @staticmethod
    def prompt_cache_key(namespace: str, model_id: str, release_id: str) -> str:
        digest = hashlib.sha256(
            f"AI-STUDIO-PROMPT-v1|{namespace}|{model_id}|{release_id}".encode()
        ).hexdigest()[:32]
        return f"ai-studio-{namespace}-{digest}"[:64]

    def create_response(
        self,
        *,
        idempotency_key: str,
        max_attempts: int,
        **kwargs: Any,
    ) -> Any:
        if max_attempts < 1 or max_attempts > self.maximum_attempts:
            raise ValueError("provider attempts exceed the configured retry policy")
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                return self.raw_client().responses.create(
                    **kwargs,
                    extra_headers={"Idempotency-Key": idempotency_key[:128]},
                )
            except Exception as error:
                last_error = error
                if not _transient(error) or attempt + 1 >= max_attempts:
                    raise ProviderRequestError(_category(error)) from error
                self._sleep(self.retry_initial_backoff_seconds * (2**attempt))
        raise ProviderRequestError("provider_unavailable") from last_error

    def search_vector_store(
        self,
        *,
        vector_store_id: str,
        query: str,
        filters: dict[str, Any],
        max_num_results: int,
    ) -> Any:
        try:
            return self.raw_client().vector_stores.search(
                vector_store_id=vector_store_id,
                query=query,
                filters=filters,
                max_num_results=max_num_results,
                rewrite_query=True,
            )
        except Exception as error:
            raise ProviderRequestError(_category(error)) from error
