"""Unified AI provider abstraction.

Every concrete provider (OpenAI, Gemini, Claude, Ollama) implements this
interface over direct HTTP calls (via ``httpx``), so the rest of Cosmya
never needs to know provider-specific request/response shapes.
"""

from __future__ import annotations

import abc
import asyncio
import re
from collections.abc import AsyncIterator

import httpx

from cosmya.ai.errors import (
    AuthenticationError,
    NetworkError,
    ProviderError,
    RateLimitError,
)
from cosmya.ai.models import ChatMessage, CompletionResult, ModelInfo, ToolDefinition
from cosmya.config.models import ProviderName

_MAX_RETRIES = 3
_RETRY_BASE_DELAY_S = 1.0
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Matches common API key shapes so they can never leak into an exception
# message or a log line, even if a provider ever echoes the request back.
_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9_\-]{10,})"
    r"|(AIza[A-Za-z0-9_\-]{10,})"
    r"|(Bearer\s+[A-Za-z0-9._\-]{10,})",
)


def redact(text: str) -> str:
    """Strip anything that looks like an API key/token out of ``text``."""
    return _SECRET_PATTERN.sub("[REDACTED]", text)


def describe_response(response: httpx.Response, *, snippet_len: int = 300) -> str:
    """A short, redacted, human-useful description of an HTTP response for
    error messages -- status code plus a truncated body snippet -- so a
    failure like "non-JSON response" says *what actually came back*
    (an HTML error page, a truncated stream, a proxy error, etc.) instead
    of leaving the person guessing.
    """
    body = redact(response.text[:snippet_len])
    if len(response.text) > snippet_len:
        body += "..."
    return f"HTTP {response.status_code}, body: {body!r}"


class AIProvider(abc.ABC):
    """Base class every provider adapter must implement."""

    name: ProviderName

    def __init__(
        self, api_key: str | None = None, *, base_url: str | None = None
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url

    @abc.abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Query the provider and return the models available to the account."""

    @abc.abstractmethod
    async def complete(
        self,
        model_id: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> CompletionResult:
        """Run one non-streaming completion turn, possibly returning tool calls."""

    async def stream(
        self,
        model_id: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[str]:
        """Default streaming fallback: yield the full text of a non-streamed call.

        Providers that support real token streaming should override this.
        """
        result = await self.complete(model_id, messages, tools)
        if result.text:
            yield result.text

    async def test_connection(self) -> bool:
        """Lightweight reachability/credential check. Overridable per provider."""
        try:
            await self.list_models()
            return True
        except ProviderError:
            return False

    async def _request_with_retries(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Issue an HTTP request with bounded retries on transient failures.

        Auth failures (401/403) are never retried. Secrets are stripped from
        any raised error message.
        """
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await client.request(method, url, **kwargs)
            except httpx.TimeoutException:
                last_error = NetworkError(
                    redact(f"Request to {self.name.value} timed out.")
                )
            except httpx.RequestError as exc:
                last_error = NetworkError(
                    redact(f"Network error contacting {self.name.value}: {exc}")
                )
            else:
                if response.status_code in (401, 403):
                    raise AuthenticationError(
                        f"{self.name.display_label} rejected the API key "
                        f"(HTTP {response.status_code})."
                    )
                if response.status_code == 429:
                    last_error = RateLimitError(
                        f"{self.name.display_label} rate-limited this request."
                    )
                elif response.status_code in _RETRYABLE_STATUS_CODES:
                    last_error = ProviderError(
                        redact(
                            f"{self.name.display_label} returned HTTP "
                            f"{response.status_code}."
                        )
                    )
                else:
                    return response

            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_BASE_DELAY_S * (2**attempt))

        assert last_error is not None
        raise last_error
