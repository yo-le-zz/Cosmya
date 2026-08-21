"""Google Gemini provider adapter (direct HTTPS calls, no SDK dependency)."""

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

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class GeminiProvider(AIProvider):
    name = ProviderName.GEMINI

    def _require_key(self) -> str:
        if not self._api_key:
            raise AuthenticationError("No Gemini API key configured.")
        return self._api_key

    async def list_models(self) -> list[ModelInfo]:
        key = self._require_key()
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request_with_retries(
                client, "GET", f"{_API_BASE}/models", params={"key": key}
            )
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise InvalidResponseError(
                    "Gemini returned a non-JSON model list."
                ) from exc

        models: list[ModelInfo] = []
        for item in payload.get("models", []):
            methods = item.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            raw_name = item.get("name", "")  # e.g. "models/gemini-2.5-pro"
            model_id = raw_name.split("/", 1)[-1] if "/" in raw_name else raw_name
            models.append(
                ModelInfo(
                    id=model_id,
                    display_name=item.get("displayName", model_id),
                    provider=self.name,
                    metadata={"description": item.get("description", "")},
                )
            )
        return sorted(models, key=lambda m: m.id)

    async def complete(
        self,
        model_id: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> CompletionResult:
        key = self._require_key()
        system_text, contents = _split_system_and_contents(messages)

        body: dict = {"contents": contents}
        if system_text:
            body["systemInstruction"] = {"parts": [{"text": system_text}]}
        if tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.parameters,
                        }
                        for t in tools
                    ]
                }
            ]

        url = f"{_API_BASE}/models/{model_id}:generateContent"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request_with_retries(
                client, "POST", url, params={"key": key}, json=body
            )
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise InvalidResponseError(
                    redact("Gemini returned a non-JSON completion response.")
                ) from exc

        try:
            candidate = payload["candidates"][0]
            parts = candidate["content"]["parts"]
        except (KeyError, IndexError) as exc:
            raise InvalidResponseError(
                redact(f"Unexpected Gemini response shape: {payload}")
            ) from exc

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for i, part in enumerate(parts):
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(
                    ToolCall(
                        id=f"call_{i}", name=fc["name"], arguments=fc.get("args", {})
                    )
                )

        return CompletionResult(
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            finish_reason=candidate.get("finishReason", "STOP"),
            raw_model_id=model_id,
        )


def _split_system_and_contents(messages: list[ChatMessage]) -> tuple[str, list[dict]]:
    system_parts: list[str] = []
    contents: list[dict] = []
    for message in messages:
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
            continue
        if message.role == "tool" and message.tool_result:
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": message.tool_result.name,
                                "response": message.tool_result.content,
                            }
                        }
                    ],
                }
            )
            continue
        role = "model" if message.role == "assistant" else "user"
        parts: list[dict] = []
        if message.content:
            parts.append({"text": message.content})
        for tc in message.tool_calls:
            parts.append({"functionCall": {"name": tc.name, "args": tc.arguments}})
        contents.append({"role": role, "parts": parts or [{"text": ""}]})
    return "\n\n".join(system_parts), contents
