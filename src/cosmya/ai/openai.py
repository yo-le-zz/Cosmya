"""OpenAI provider adapter (direct HTTPS calls, no SDK dependency)."""

from __future__ import annotations

import json

import httpx

from cosmya.ai.errors import AuthenticationError, InvalidResponseError
from cosmya.ai.models import (
    ChatMessage,
    CompletionResult,
    ModelInfo,
    ToolCall,
    ToolDefinition,
)
from cosmya.ai.provider import AIProvider, redact
from cosmya.config.models import ProviderName

_API_BASE = "https://api.openai.com/v1"
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

# Chat-capable model id prefixes; OpenAI's /models endpoint also lists
# embedding/whisper/tts/moderation models that are not usable for chat.
_CHAT_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt-")
_EXCLUDED_SUBSTRINGS = (
    "embedding",
    "whisper",
    "tts",
    "moderation",
    "audio",
    "realtime",
    "image",
)


class OpenAIProvider(AIProvider):
    name = ProviderName.OPENAI

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise AuthenticationError("No OpenAI API key configured.")
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def list_models(self) -> list[ModelInfo]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request_with_retries(
                client, "GET", f"{_API_BASE}/models", headers=self._headers()
            )
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise InvalidResponseError(
                    "OpenAI returned a non-JSON model list."
                ) from exc

        models: list[ModelInfo] = []
        for item in payload.get("data", []):
            model_id = item.get("id", "")
            if not model_id.startswith(_CHAT_MODEL_PREFIXES):
                continue
            if any(bad in model_id for bad in _EXCLUDED_SUBSTRINGS):
                continue
            models.append(
                ModelInfo(
                    id=model_id,
                    display_name=model_id,
                    provider=self.name,
                    metadata={"owned_by": item.get("owned_by", "")},
                )
            )
        return sorted(models, key=lambda m: m.id)

    async def complete(
        self,
        model_id: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> CompletionResult:
        body = {
            "model": model_id,
            "messages": [_to_openai_message(m) for m in messages],
        }
        if tools:
            body["tools"] = [_to_openai_tool(t) for t in tools]

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request_with_retries(
                client,
                "POST",
                f"{_API_BASE}/chat/completions",
                headers=self._headers(),
                json=body,
            )
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise InvalidResponseError(
                    redact("OpenAI returned a non-JSON completion response.")
                ) from exc

        try:
            choice = payload["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError) as exc:
            raise InvalidResponseError(
                redact(f"Unexpected OpenAI response shape: {payload}")
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


def _to_openai_message(message: ChatMessage) -> dict:
    if message.role == "tool" and message.tool_result:
        return {
            "role": "tool",
            "tool_call_id": message.tool_result.tool_call_id,
            "content": json.dumps(message.tool_result.content),
        }
    out: dict = {"role": message.role, "content": message.content or ""}
    if message.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in message.tool_calls
        ]
    return out


def _to_openai_tool(tool: ToolDefinition) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
