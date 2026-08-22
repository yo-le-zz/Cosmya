"""Maps :class:`ProviderName` to concrete provider adapter classes."""

from __future__ import annotations

from cosmya.ai.claude import ClaudeProvider
from cosmya.ai.gemini import GeminiProvider
from cosmya.ai.ollama import OllamaProvider
from cosmya.ai.openai import OpenAIProvider
from cosmya.ai.openai_compatible import (
    CerebrasProvider,
    DeepSeekProvider,
    FireworksProvider,
    GroqProvider,
    MistralProvider,
    OpenRouterProvider,
    TogetherProvider,
    XAIProvider,
)
from cosmya.ai.provider import AIProvider
from cosmya.config.models import ProviderName

_PROVIDER_CLASSES: dict[ProviderName, type[AIProvider]] = {
    ProviderName.OPENAI: OpenAIProvider,
    ProviderName.GEMINI: GeminiProvider,
    ProviderName.CLAUDE: ClaudeProvider,
    ProviderName.OLLAMA: OllamaProvider,
    ProviderName.GROQ: GroqProvider,
    ProviderName.OPENROUTER: OpenRouterProvider,
    ProviderName.MISTRAL: MistralProvider,
    ProviderName.DEEPSEEK: DeepSeekProvider,
    ProviderName.XAI: XAIProvider,
    ProviderName.TOGETHER: TogetherProvider,
    ProviderName.FIREWORKS: FireworksProvider,
    ProviderName.CEREBRAS: CerebrasProvider,
}

_unregistered = set(ProviderName) - set(_PROVIDER_CLASSES)
if _unregistered:
    raise RuntimeError(
        f"ProviderName value(s) with no registered adapter class: {_unregistered}. "
        "Every ProviderName must be mapped in ai/registry.py."
    )


def create_provider(name: ProviderName, api_key: str | None = None) -> AIProvider:
    provider_class = _PROVIDER_CLASSES[name]
    return provider_class(api_key=api_key)
