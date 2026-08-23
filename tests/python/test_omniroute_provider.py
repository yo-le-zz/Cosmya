import httpx
import pytest
import respx

from cosmya.ai.errors import AuthenticationError
from cosmya.ai.models import ChatMessage
from cosmya.ai.openai_compatible import OMNIROUTE_AUTO_MODEL_LABELS, OmniRouteProvider
from cosmya.ai.registry import create_provider
from cosmya.config.models import ProviderName


def test_omniroute_requires_api_key():
    assert ProviderName.OMNIROUTE.requires_api_key is True


@pytest.mark.asyncio
async def test_list_models_without_api_key_raises_authentication_error():
    provider = OmniRouteProvider(api_key=None)
    with pytest.raises(AuthenticationError):
        await provider.list_models()


@pytest.mark.asyncio
@respx.mock
async def test_list_models_returns_curated_auto_aliases_not_full_catalog():
    """OmniRoute's real catalog can list 1000+ upstream models -- Cosmya
    must never dump that whole list into the model-selection menu.
    list_models() should return only the small set of documented `auto`
    routing aliases, regardless of what the live endpoint returns."""
    respx.get("http://localhost:20128/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": f"upstream-model-{i}"} for i in range(1500)]},
        )
    )
    provider = OmniRouteProvider(api_key="test-key")
    models = await provider.list_models()

    assert len(models) == len(OMNIROUTE_AUTO_MODEL_LABELS)
    ids = {m.id for m in models}
    assert ids == set(OMNIROUTE_AUTO_MODEL_LABELS)
    assert "auto" in ids
    # None of the 1500 fake upstream models leaked through.
    assert not any(m.id.startswith("upstream-model-") for m in models)


@pytest.mark.asyncio
@respx.mock
async def test_list_models_still_performs_real_connectivity_check():
    """Even though the returned list is curated/static, a bad key or an
    unreachable gateway must still surface as a real error -- the
    connectivity check must not become a no-op."""
    respx.get("http://localhost:20128/v1/models").mock(return_value=httpx.Response(401))
    provider = OmniRouteProvider(api_key="bad-key")
    with pytest.raises(AuthenticationError):
        await provider.list_models()


@pytest.mark.asyncio
@respx.mock
async def test_authorization_header_sent_with_api_key():
    route = respx.get("http://localhost:20128/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    provider = OmniRouteProvider(api_key="my-key")
    await provider.list_models()
    assert route.calls[0].request.headers["Authorization"] == "Bearer my-key"


def test_default_base_url_is_local_gateway():
    provider = OmniRouteProvider(api_key="k")
    assert provider.api_base == "http://localhost:20128/v1"


def test_custom_base_url_overrides_default():
    """Supports OmniRoute's Remote Mode, which drives a non-local instance."""
    provider = OmniRouteProvider(api_key="tok", base_url="https://my-omniroute.example.com/v1")
    assert provider.api_base == "https://my-omniroute.example.com/v1"


@pytest.mark.asyncio
@respx.mock
async def test_complete_works_with_auto_model_id():
    respx.post("http://localhost:20128/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "auto",
                "choices": [{"finish_reason": "stop", "message": {"content": "hi there"}}],
            },
        )
    )
    provider = OmniRouteProvider(api_key="k")
    result = await provider.complete("auto", [ChatMessage(role="user", content="hi")], [])
    assert result.text == "hi there"


def test_registry_creates_omniroute_provider():
    provider = create_provider(ProviderName.OMNIROUTE, "k")
    assert isinstance(provider, OmniRouteProvider)


def test_auto_is_the_first_curated_model():
    """'auto' must be first so it's the natural default when the model
    list is displayed."""
    assert next(iter(OMNIROUTE_AUTO_MODEL_LABELS)) == "auto"
