"""Shared adapter for providers that expose an OpenAI-compatible REST API.

Groq, OpenRouter, Mistral, DeepSeek, xAI, Together AI, Fireworks AI,
Cerebras, and OmniRoute all implement the same wire format OpenAI does for
``GET /models`` and ``POST /chat/completions`` (this is a de facto industry
convention, not a coincidence -- it's what lets people point existing
OpenAI-SDK code at a different base URL). Rather than duplicating
``cosmya.ai.openai``'s request/response handling for each one, every one of
these providers is a thin subclass of :class:`OpenAICompatibleProvider`
that only sets an API base URL (and, rarely, a couple of extra headers, or
for OmniRoute, a curated model list -- see that class's docstring). The
message/tool wire-format conversion helpers are imported directly from
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
from cosmya.ai.provider import AIProvider, describe_response, redact
from cosmya.config.models import ProviderName

_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def _looks_free(entry: dict) -> bool:
    """Best-effort free-tier detection for one catalog entry from any
    OpenAI-compatible provider's ``/models`` response.

    The bare OpenAI model-list schema carries no pricing field at all, so
    this only works for providers/entries that voluntarily expose one of
    the following signals (checked in order): an explicit ``free``/
    ``is_free`` boolean; a ``pricing`` object (an extension several
    OpenAI-compatible gateways -- notably OpenRouter, and OmniRoute for
    OpenRouter-sourced entries -- add) where every present cost field is
    zero; or OpenRouter's own ``:free`` id suffix convention. An entry
    exposing none of these signals is treated as *not confirmed free*,
    never as *assumed free* -- most providers here (Groq, Mistral,
    DeepSeek, xAI, Together AI, Fireworks AI, Cerebras) don't expose
    pricing via this endpoint at all, so their models will consistently
    read as not-confirmed-free, which is the honest answer, not a defect.
    """
    for key in ("free", "is_free", "isFree"):
        value = entry.get(key)
        if isinstance(value, bool):
            return value

    pricing = entry.get("pricing")
    if isinstance(pricing, dict):
        cost_fields = [
            pricing[k]
            for k in ("prompt", "completion", "input", "output", "request", "image")
            if k in pricing
        ]
        if cost_fields:
            return all(_is_zero_cost(v) for v in cost_fields)

    model_id = entry.get("id", "")
    if isinstance(model_id, str) and model_id.endswith(":free"):
        return True

    return False


def _is_zero_cost(value: object) -> bool:
    try:
        return float(value) == 0.0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


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
                    f"{self.name.display_label} returned a non-JSON model list "
                    f"({describe_response(response)})."
                ) from exc

        models = [
            ModelInfo(
                id=item["id"],
                display_name=item.get("name", item["id"]),
                provider=self.name,
                metadata={"owned_by": item.get("owned_by", ""), "free": _looks_free(item)},
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
                    redact(
                        f"{self.name.display_label} returned a non-JSON completion "
                        f"response ({describe_response(response)})."
                    )
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


OMNIROUTE_AUTO_MODEL_LABELS: dict[str, str] = {
    "auto": "Auto (balanced default)",
    "auto/coding": "Auto — coding-optimized",
    "auto/fast": "Auto — lowest latency",
    "auto/cheap": "Auto — cheapest per token",
    "auto/offline": "Auto — most quota headroom",
    "auto/smart": "Auto — quality + exploration",
}


class OmniRouteProvider(OpenAICompatibleProvider):
    """OmniRoute (https://github.com/diegosouzapw/OmniRoute) is a
    self-hosted AI gateway you run locally that itself fans out to
    hundreds of upstream providers behind one OpenAI-compatible endpoint.
    From Cosmya's point of view it's just another OpenAI-compatible
    provider, requiring an API key like the rest.

    OmniRoute's own live catalog can list 1000+ upstream models, which
    would make Cosmya's single flat model-selection list unusable. Rather
    than surface that whole catalog, :meth:`list_models` still performs
    the real network call (so a bad key or unreachable gateway is still
    caught exactly as for every other provider) but returns only
    OmniRoute's own documented ``auto`` routing aliases -- which is what
    you actually want to pick day to day, since OmniRoute chooses the
    concrete upstream model for you.
    """

    name = ProviderName.OMNIROUTE
    api_base = "http://localhost:20128/v1"

    def __init__(self, api_key: str | None = None, *, base_url: str | None = None) -> None:
        super().__init__(api_key=api_key, base_url=base_url)
        if base_url:
            self.api_base = base_url

    async def list_models(self) -> list[ModelInfo]:
        await super().list_models()  # connectivity/auth check; result discarded
        return [
            ModelInfo(id=model_id, display_name=label, provider=self.name)
            for model_id, label in OMNIROUTE_AUTO_MODEL_LABELS.items()
        ]

    async def list_catalog_models(self, *, free_only: bool = True) -> list[ModelInfo]:
        """Fetch OmniRoute's real upstream catalog -- the full 1000+-model
        list :meth:`list_models` deliberately hides -- for people who want
        to pick a specific provider/model instead of an ``auto`` alias.

        Free detection is BEST-EFFORT. OmniRoute's public ``GET /v1/models``
        is documented only as "OpenAI format"; the bare OpenAI model-list
        schema carries no pricing field at all. This looks for whichever of
        the following signals a given entry actually provides, in order:
        an explicit ``free``/``is_free`` boolean; a ``pricing`` object
        (an extension several OpenAI-compatible gateways add) where every
        present cost field is zero; or OpenRouter's own ``:free`` id
        suffix convention (which OmniRoute would preserve verbatim for
        OpenRouter-sourced models, since it proxies ids through as-is). A
        model exposing none of these signals is treated as *not confirmed
        free* -- excluded when ``free_only=True`` -- rather than assumed
        free either way. OmniRoute's own dashboard
        (``/dashboard/free-tiers``) is the authoritative source if this
        ever mis-classifies something; Cosmya has no access to that
        dashboard's data.
        """
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request_with_retries(
                client, "GET", f"{self.api_base}/models", headers=self._headers()
            )
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise InvalidResponseError(
                    f"OmniRoute returned a non-JSON model list ({describe_response(response)})."
                ) from exc

        models: list[ModelInfo] = []
        for entry in payload.get("data", []):
            model_id = entry.get("id")
            if not model_id:
                continue
            is_free = _looks_free(entry)
            if free_only and not is_free:
                continue
            models.append(
                ModelInfo(
                    id=model_id,
                    display_name=f"{model_id} \U0001f193" if is_free else model_id,
                    provider=self.name,
                    metadata={"free": is_free},
                )
            )
        return models
