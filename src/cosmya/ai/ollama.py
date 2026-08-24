"""Ollama provider adapter -- talks to a local Ollama daemon over HTTP.

Ollama does not require an API key. If the daemon is not running, this
raises :class:`ProviderUnavailableError` rather than an authentication
error, since there is no credential to be wrong about.
"""

from __future__ import annotations

import json

import httpx

from cosmya.ai.errors import InvalidResponseError, ProviderUnavailableError
from cosmya.ai.models import (
    ChatMessage,
    CompletionResult,
    ModelInfo,
    ToolCall,
    ToolDefinition,
)
from cosmya.ai.provider import AIProvider, redact
from cosmya.config.models import ProviderName

_DEFAULT_BASE_URL = "http://localhost:11434"
_TIMEOUT = httpx.Timeout(180.0, connect=5.0)


class OllamaProvider(AIProvider):
    name = ProviderName.OLLAMA

    def __init__(
        self, api_key: str | None = None, *, base_url: str | None = None
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url or _DEFAULT_BASE_URL)

    async def list_models(self) -> list[ModelInfo]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                response = await client.get(f"{self._base_url}/api/tags")
            except httpx.RequestError as exc:
                raise ProviderUnavailableError(
                    redact(
                        "Ollama is not reachable. Make sure the Ollama daemon "
                        f"is running at {self._base_url}. ({exc})"
                    )
                ) from exc

            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise InvalidResponseError(
                    "Ollama returned a non-JSON model list."
                ) from exc

        models = [
            ModelInfo(
                id=item["name"],
                display_name=item["name"],
                provider=self.name,
                # Ollama runs locally against your own hardware -- there
                # is no per-token API cost, so every model it reports is
                # unambiguously free (unlike the best-effort heuristic
                # used for cloud providers where pricing isn't exposed).
                metadata={"size": item.get("size", 0), "free": True},
            )
            for item in payload.get("models", [])
        ]
        return sorted(models, key=lambda m: m.id)

    async def complete(
        self,
        model_id: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> CompletionResult:
        body: dict = {
            "model": model_id,
            "messages": [_to_ollama_message(m) for m in messages],
            "stream": False,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                response = await client.post(f"{self._base_url}/api/chat", json=body)
            except httpx.RequestError as exc:
                raise ProviderUnavailableError(
                    redact(f"Ollama is not reachable at {self._base_url}. ({exc})")
                ) from exc

            if response.status_code == 404:
                raise InvalidResponseError(
                    f"Ollama model '{model_id}' is not installed locally. "
                    f"Run `ollama pull {model_id}` first."
                )

            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise InvalidResponseError(
                    redact("Ollama returned a non-JSON completion response.")
                ) from exc

        message = payload.get("message", {})
        tool_calls = [
            ToolCall(
                id=f"call_{i}",
                name=tc["function"]["name"],
                arguments=tc["function"].get("arguments", {}),
            )
            for i, tc in enumerate(message.get("tool_calls") or [])
        ]

        return CompletionResult(
            text=message.get("content") or None,
            tool_calls=tool_calls,
            finish_reason="stop" if payload.get("done", True) else "incomplete",
            raw_model_id=payload.get("model", model_id),
        )

    async def test_connection(self) -> bool:
        try:
            await self.list_models()
            return True
        except ProviderUnavailableError:
            return False


def _to_ollama_message(message: ChatMessage) -> dict:
    if message.role == "tool" and message.tool_result:
        return {"role": "tool", "content": json.dumps(message.tool_result.content)}
    return {"role": message.role, "content": message.content or ""}
