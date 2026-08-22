"""Shared adapter for providers that expose an OpenAI-compatible REST API.

Groq, OpenRouter, Mistral, DeepSeek, xAI, Together AI, Fireworks AI, and
Cerebras all implement the same wire format OpenAI does for
``GET /models`` and ``POST /chat/completions`` (this is a de facto industry
convention, not a coincidence -- it's what lets people point existing
OpenAI-SDK code at a different base URL). Rather than duplicating
``cosmya.ai.openai``'s request/response handling eight times, every one of
these providers is a thin subclass of :class:`OpenAICompatibleProvider`
that only sets an API base URL (and, rarely, a couple of extra headers).
The message/tool wire-format conversion helpers are imported directly from
``cosmya.ai.openai`` so there is exactly one implementation of that format
in the codebase.

Cosmya's own architecture is unaffected either way: every provider here
still implements the same :class:`~cosmya.ai.provider.AIProvider`
interface, still goes through :func:`~cosmya.ai.provider.AIProvider._request_with_retries`
for retries/redaction, and the rest of Cosmya never knows or cares that
these providers share code -- see ``PROVIDER CONFIGURATION FLOW`` etc.,
which only ever talk to the ``AIProvider`` interface.
"""

from __future__ import annotations

import json

import httpx

from cosmya.ai.errors import AuthenticationError, InvalidResponseError
from cosmya.ai.models import ChatMessage, CompletionResult, ModelInfo, ToolCall, ToolDefinition
from cosmya.ai.openai import to_openai_message, to_openai_tool
from cosmya.ai.provider import AIProvider, redact
from cosmya.config.models import ProviderName

_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class OpenAICompatibleProvider(AIProvider):
    """Base class for OpenAI-wire-format providers. Subclasses set
    ``name`` and ``api_base``; ``extra_headers`` is optional."""

    api_base: str = ""
    extra_headers: dict[str, str] = {}

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise AuthenticationError(f"No {self.name.display_label} API key configured.")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.extra_headers)
        return headers

    async def list_models(self) -> list[ModelInfo]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request_with_retries(
                client, "GET", f"{self.api_base}/models", headers=self._headers()
            )
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise InvalidResponseError(
                    f"{self.name.display_label} returned a non-JSON model list."
                ) from exc

        models = [
            ModelInfo(
                id=item["id"],
                display_name=item.get("name", item["id"]),
                provider=self.name,
                metadata={"owned_by": item.get("owned_by", "")},
            )
            for item in payload.get("data", [])
            if "id" in item
        ]
        return sorted(models, key=lambda m: m.id)

    async def complete(
        self,
        model_id: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> CompletionResult:
        body = {
            "model": model_id,
            "messages": [to_openai_message(m) for m in messages],
        }
        if tools:
            body["tools"] = [to_openai_tool(t) for t in tools]

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request_with_retries(
                client,
                "POST",
                f"{self.api_base}/chat/completions",
                headers=self._headers(),
                json=body,
            )
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise InvalidResponseError(
                    redact(f"{self.name.display_label} returned a non-JSON completion response.")
                ) from exc

        try:
            choice = payload["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError) as exc:
            raise InvalidResponseError(
                redact(f"Unexpected {self.name.display_label} response shape: {payload}")
            ) from exc

        tool_calls = [
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=json.loads(tc["function"]["arguments"] or "{}"),
            )
            for tc in message.get("tool_calls") or []
        ]

        return CompletionResult(
            text=message.get("content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            raw_model_id=payload.get("model", model_id),
        )


class GroqProvider(OpenAICompatibleProvider):
    name = ProviderName.GROQ
    api_base = "https://api.groq.com/openai/v1"


class OpenRouterProvider(OpenAICompatibleProvider):
    name = ProviderName.OPENROUTER
    api_base = "https://openrouter.ai/api/v1"
    # Optional but recommended by OpenRouter so usage is attributed to
    # Cosmya rather than showing up as an anonymous client in their logs.
    extra_headers = {
        "HTTP-Referer": "https://cosmya.pages.dev/",
        "X-Title": "Cosmya",
    }


class MistralProvider(OpenAICompatibleProvider):
    name = ProviderName.MISTRAL
    api_base = "https://api.mistral.ai/v1"


class DeepSeekProvider(OpenAICompatibleProvider):
    name = ProviderName.DEEPSEEK
    api_base = "https://api.deepseek.com/v1"


class XAIProvider(OpenAICompatibleProvider):
    name = ProviderName.XAI
    api_base = "https://api.x.ai/v1"


class TogetherProvider(OpenAICompatibleProvider):
    name = ProviderName.TOGETHER
    api_base = "https://api.together.xyz/v1"


class FireworksProvider(OpenAICompatibleProvider):
    name = ProviderName.FIREWORKS
    api_base = "https://api.fireworks.ai/inference/v1"


class CerebrasProvider(OpenAICompatibleProvider):
    name = ProviderName.CEREBRAS
    api_base = "https://api.cerebras.ai/v1"
