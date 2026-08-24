"""Provider-agnostic data types shared by every AI provider adapter."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from cosmya.config.models import ProviderName


class ModelInfo(BaseModel):
    """A normalized description of one model offered by a provider."""

    id: str
    display_name: str
    provider: ProviderName
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def label(self) -> str:
        return f"{self.display_name} ({self.provider.display_label})"


class ToolCall(BaseModel):
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]
    # Provider-specific extras that must be preserved and echoed back
    # verbatim in a later request for that provider's API to keep working
    # correctly across multi-turn tool calling. Currently used by Gemini
    # for `thoughtSignature` (see ai/gemini.py) -- Gemini's API rejects a
    # later request that's missing it on a replayed functionCall part.
    # Every other provider ignores this field entirely.
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolResultMessage(BaseModel):
    """The result of executing a ToolCall, sent back to the model."""

    tool_call_id: str
    name: str
    content: dict[str, Any]


class ChatMessage(BaseModel):
    """One message in the conversation sent to a provider."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_result: ToolResultMessage | None = None


class ToolDefinition(BaseModel):
    """A tool the model is allowed to call, described with a JSON schema."""

    name: str
    description: str
    parameters: dict[str, Any]


class CompletionResult(BaseModel):
    """The outcome of one turn of a chat completion request."""

    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str = "stop"
    raw_model_id: str = ""


class ProviderStatus(BaseModel):
    provider: ProviderName
    configured: bool
    reachable: bool | None = None
    detail: str = ""
