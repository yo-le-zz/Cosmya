import httpx
import pytest
import respx

from cosmya.ai.errors import AuthenticationError
from cosmya.ai.openai_compatible import OmniRouteProvider, _is_zero_cost, _looks_free


class TestLooksFree:
    def test_explicit_true_flag(self):
        assert _looks_free({"id": "x", "free": True}) is True

    def test_explicit_false_flag(self):
        assert _looks_free({"id": "x", "free": False}) is False

    def test_is_free_camel_case_variant(self):
        assert _looks_free({"id": "x", "isFree": True}) is True

    def test_zero_pricing_object(self):
        entry = {"id": "x", "pricing": {"prompt": "0", "completion": "0"}}
        assert _looks_free(entry) is True

    def test_nonzero_pricing_object(self):
        entry = {"id": "x", "pricing": {"prompt": "0.002", "completion": "0.006"}}
        assert _looks_free(entry) is False

    def test_mixed_zero_and_nonzero_pricing_is_not_free(self):
        entry = {"id": "x", "pricing": {"prompt": "0", "completion": "0.006"}}
        assert _looks_free(entry) is False

    def test_openrouter_free_suffix(self):
        entry = {"id": "meta-llama/llama-3.1-8b-instruct:free"}
        assert _looks_free(entry) is True

    def test_no_signal_present_defaults_to_not_confirmed_free(self):
        entry = {"id": "openai/gpt-5.4"}
        assert _looks_free(entry) is False

    def test_numeric_pricing_values_not_just_strings(self):
        entry = {"id": "x", "pricing": {"prompt": 0, "completion": 0}}
        assert _looks_free(entry) is True


class TestIsZeroCost:
    def test_zero_string(self):
        assert _is_zero_cost("0") is True

    def test_zero_float(self):
        assert _is_zero_cost(0.0) is True

    def test_nonzero(self):
        assert _is_zero_cost("0.001") is False

    def test_non_numeric_is_not_zero_cost(self):
        assert _is_zero_cost("free") is False

    def test_none_is_not_zero_cost(self):
        assert _is_zero_cost(None) is False


@pytest.mark.asyncio
@respx.mock
async def test_list_catalog_models_free_only_filters_out_paid():
    respx.get("http://localhost:20128/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "oc/free-model", "free": True},
                    {"id": "openai/gpt-5.4", "pricing": {"prompt": "0.01", "completion": "0.03"}},
                    {"id": "or/meta-llama:free"},
                ]
            },
        )
    )
    provider = OmniRouteProvider(api_key="k")
    models = await provider.list_catalog_models(free_only=True)
    ids = {m.id for m in models}
    assert ids == {"oc/free-model", "or/meta-llama:free"}
    assert "openai/gpt-5.4" not in ids


@pytest.mark.asyncio
@respx.mock
async def test_list_catalog_models_free_only_false_returns_everything():
    respx.get("http://localhost:20128/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "oc/free-model", "free": True},
                    {"id": "openai/gpt-5.4", "pricing": {"prompt": "0.01", "completion": "0.03"}},
                ]
            },
        )
    )
    provider = OmniRouteProvider(api_key="k")
    models = await provider.list_catalog_models(free_only=False)
    assert {m.id for m in models} == {"oc/free-model", "openai/gpt-5.4"}


@pytest.mark.asyncio
@respx.mock
async def test_list_catalog_models_marks_free_metadata():
    respx.get("http://localhost:20128/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "oc/free-model", "free": True}]})
    )
    provider = OmniRouteProvider(api_key="k")
    models = await provider.list_catalog_models(free_only=False)
    assert models[0].metadata["free"] is True
    assert "\U0001f193" in models[0].display_name  # free marker emoji


@pytest.mark.asyncio
@respx.mock
async def test_list_catalog_models_skips_entries_without_id():
    respx.get("http://localhost:20128/v1/models").mock(
        return_value=httpx.Response(
            200, json={"data": [{"free": True}, {"id": "oc/valid", "free": True}]}
        )
    )
    provider = OmniRouteProvider(api_key="k")
    models = await provider.list_catalog_models(free_only=True)
    assert [m.id for m in models] == ["oc/valid"]


@pytest.mark.asyncio
async def test_list_catalog_models_without_api_key_raises():
    provider = OmniRouteProvider(api_key=None)
    with pytest.raises(AuthenticationError):
        await provider.list_catalog_models()


@pytest.mark.asyncio
@respx.mock
async def test_list_catalog_models_does_not_affect_list_models():
    """list_models() must remain the curated 6-alias list regardless of
    what the catalog contains -- list_catalog_models is a separate,
    explicit opt-in path."""
    from cosmya.ai.openai_compatible import OMNIROUTE_AUTO_MODEL_LABELS

    respx.get("http://localhost:20128/v1/models").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": f"upstream-{i}"} for i in range(50)]}
        )
    )
    provider = OmniRouteProvider(api_key="k")
    default_models = await provider.list_models()
    assert len(default_models) == len(OMNIROUTE_AUTO_MODEL_LABELS)
