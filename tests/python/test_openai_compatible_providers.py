import httpx
import pytest
import respx

from cosmya.ai.errors import AuthenticationError
from cosmya.ai.models import ChatMessage
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
from cosmya.ai.registry import create_provider
from cosmya.config.models import ProviderName

# (provider class, expected api_base, ProviderName) for every OpenAI-
# compatible adapter. Parametrizing over this list means each of the eight
# providers gets the exact same behavioral coverage without eight copies of
# every test.
COMPATIBLE_PROVIDERS = [
    (GroqProvider, "https://api.groq.com/openai/v1", ProviderName.GROQ),
    (OpenRouterProvider, "https://openrouter.ai/api/v1", ProviderName.OPENROUTER),
    (MistralProvider, "https://api.mistral.ai/v1", ProviderName.MISTRAL),
    (DeepSeekProvider, "https://api.deepseek.com/v1", ProviderName.DEEPSEEK),
    (XAIProvider, "https://api.x.ai/v1", ProviderName.XAI),
    (TogetherProvider, "https://api.together.xyz/v1", ProviderName.TOGETHER),
    (FireworksProvider, "https://api.fireworks.ai/inference/v1", ProviderName.FIREWORKS),
    (CerebrasProvider, "https://api.cerebras.ai/v1", ProviderName.CEREBRAS),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_cls,api_base,provider_name", COMPATIBLE_PROVIDERS)
@respx.mock
async def test_list_models_normalizes(provider_cls, api_base, provider_name):
    respx.get(f"{api_base}/models").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": "some-model", "owned_by": "vendor"}]},
        )
    )
    provider = provider_cls(api_key="test-key")
    models = await provider.list_models()
    assert len(models) == 1
    assert models[0].id == "some-model"
    assert models[0].provider == provider_name


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_cls,api_base,provider_name", COMPATIBLE_PROVIDERS)
async def test_missing_api_key_raises_authentication_error(provider_cls, api_base, provider_name):
    provider = provider_cls(api_key=None)
    with pytest.raises(AuthenticationError):
        await provider.list_models()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_cls,api_base,provider_name", COMPATIBLE_PROVIDERS)
@respx.mock
async def test_401_raises_authentication_error(provider_cls, api_base, provider_name):
    respx.get(f"{api_base}/models").mock(return_value=httpx.Response(401))
    provider = provider_cls(api_key="bad-key")
    with pytest.raises(AuthenticationError):
        await provider.list_models()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_cls,api_base,provider_name", COMPATIBLE_PROVIDERS)
@respx.mock
async def test_complete_parses_tool_calls(provider_cls, api_base, provider_name):
    respx.post(f"{api_base}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "some-model",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path": "src/main.py"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        )
    )
    provider = provider_cls(api_key="test-key")
    result = await provider.complete(
        "some-model", [ChatMessage(role="user", content="hi")], []
    )
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {"path": "src/main.py"}


@pytest.mark.asyncio
@respx.mock
async def test_openrouter_sends_extra_headers():
    route = respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    provider = OpenRouterProvider(api_key="test-key")
    await provider.list_models()
    sent_headers = route.calls[0].request.headers
    assert sent_headers["HTTP-Referer"] == "https://cosmya.pages.dev/"
    assert sent_headers["X-Title"] == "Cosmya"


def test_registry_creates_correct_class_for_every_compatible_provider():
    for provider_cls, _api_base, provider_name in COMPATIBLE_PROVIDERS:
        assert isinstance(create_provider(provider_name, "k"), provider_cls)


def test_every_provider_name_has_a_registered_adapter():
    # Guards against a ProviderName being added without a matching adapter
    # (ai/registry.py raises at import time if this is ever violated, but a
    # dedicated test makes the guarantee explicit and keeps failing loudly
    # even if that startup check is ever weakened).
    from cosmya.ai.registry import _PROVIDER_CLASSES

    assert set(_PROVIDER_CLASSES) == set(ProviderName)


def test_all_new_providers_require_api_key():
    for _provider_cls, _api_base, provider_name in COMPATIBLE_PROVIDERS:
        assert provider_name.requires_api_key is True
