import httpx
import pytest
import respx

from cosmya.ai.openai_compatible import OmniRouteProvider
from cosmya.ai.registry import create_provider
from cosmya.config.models import ProviderName


def test_omniroute_does_not_require_api_key():
    assert ProviderName.OMNIROUTE.requires_api_key is False


@pytest.mark.asyncio
@respx.mock
async def test_list_models_succeeds_without_api_key():
    respx.get("http://localhost:20128/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "auto"}]})
    )
    provider = OmniRouteProvider(api_key=None)
    models = await provider.list_models()
    assert models[0].id == "auto"
    assert models[0].provider == ProviderName.OMNIROUTE


@pytest.mark.asyncio
@respx.mock
async def test_no_authorization_header_sent_when_no_key():
    route = respx.get("http://localhost:20128/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    provider = OmniRouteProvider(api_key=None)
    await provider.list_models()
    assert "authorization" not in {h.lower() for h in route.calls[0].request.headers.keys()}


@pytest.mark.asyncio
@respx.mock
async def test_authorization_header_sent_when_key_is_provided():
    """OmniRoute's own remote mode supports scoped bearer tokens -- Cosmya
    honors one if configured, even though it's never required."""
    route = respx.get("http://localhost:20128/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    provider = OmniRouteProvider(api_key="scoped-remote-token")
    await provider.list_models()
    assert route.calls[0].request.headers["Authorization"] == "Bearer scoped-remote-token"


def test_default_base_url_is_local_gateway():
    provider = OmniRouteProvider()
    assert provider.api_base == "http://localhost:20128/v1"


def test_custom_base_url_overrides_default():
    """Supports OmniRoute's Remote Mode, which drives a non-local instance."""
    provider = OmniRouteProvider(api_key="tok", base_url="https://my-omniroute.example.com/v1")
    assert provider.api_base == "https://my-omniroute.example.com/v1"


@pytest.mark.asyncio
@respx.mock
async def test_complete_works_without_api_key():
    from cosmya.ai.models import ChatMessage

    respx.post("http://localhost:20128/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "auto",
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "hi there"}}
                ],
            },
        )
    )
    provider = OmniRouteProvider(api_key=None)
    result = await provider.complete("auto", [ChatMessage(role="user", content="hi")], [])
    assert result.text == "hi there"


def test_registry_creates_omniroute_provider():
    provider = create_provider(ProviderName.OMNIROUTE, None)
    assert isinstance(provider, OmniRouteProvider)
