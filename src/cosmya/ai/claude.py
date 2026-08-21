"""Anthropic Claude provider adapter (direct HTTPS calls, no SDK dependency)."""

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

_API_BASE = "https://api.anthropic.com/v1"
_ANTHROPIC_VERSION = "2023-06-01"
_TIMEOUT = httpx.Timeout(120.0, connect=10.0)
_MAX_TOKENS = 8192


class ClaudeProvider(AIProvider):
    name = ProviderName.CLAUDE

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise AuthenticationError("No Claude API key configured.")
        return {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
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
                    "Claude returned a non-JSON model list."
                ) from exc

        models = [
            ModelInfo(
                id=item["id"],
                display_name=item.get("display_name", item["id"]),
                provider=self.name,
                metadata={"created_at": item.get("created_at", "")},
            )
            for item in payload.get("data", [])
        ]
        return sorted(models, key=lambda m: m.id)

    async def complete(
        self,
        model_id: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> CompletionResult:
        system_text, converted = _split_system_and_messages(messages)
        body: dict = {
            "model": model_id,
            "max_tokens": _MAX_TOKENS,
            "messages": converted,
        }
        if system_text:
            body["system"] = system_text
        if tools:
            body["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request_with_retries(
                client,
                "POST",
                f"{_API_BASE}/messages",
                headers=self._headers(),
                json=body,
            )
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise InvalidResponseError(
                    redact("Claude returned a non-JSON completion response.")
                ) from exc

        if "content" not in payload:
            raise InvalidResponseError(
                redact(f"Unexpected Claude response shape: {payload}")
            )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in payload["content"]:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block["id"],
                        name=block["name"],
                        arguments=block.get("input", {}),
                    )
                )

        return CompletionResult(
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            finish_reason=payload.get("stop_reason", "stop"),
            raw_model_id=payload.get("model", model_id),
        )


def _split_system_and_messages(messages: list[ChatMessage]) -> tuple[str, list[dict]]:
    """Claude takes the system prompt as a top-level field, not a message."""
    system_parts: list[str] = []
    converted: list[dict] = []
    for message in messages:
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
            continue
        if message.role == "tool" and message.tool_result:
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_result.tool_call_id,
                            "content": json.dumps(message.tool_result.content),
                        }
                    ],
                }
            )
            continue
        content: list[dict] = []
        if message.content:
            content.append({"type": "text", "text": message.content})
        for tc in message.tool_calls:
            content.append(
                {
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                }
            )
        converted.append({"role": message.role, "content": content or ""})
    return "\n\n".join(system_parts), converted
