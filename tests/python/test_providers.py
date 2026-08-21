import httpx
import pytest
import respx

from cosmya.ai.claude import ClaudeProvider
from cosmya.ai.errors import AuthenticationError, ProviderUnavailableError
from cosmya.ai.gemini import GeminiProvider
from cosmya.ai.models import ChatMessage
from cosmya.ai.ollama import OllamaProvider
from cosmya.ai.openai import OpenAIProvider
from cosmya.ai.registry import create_provider
from cosmya.config.models import ProviderName


@pytest.mark.asyncio
@respx.mock
async def test_openai_list_models_filters_and_normalizes():
    respx.get("https://api.openai.com/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-5", "owned_by": "openai"},
                    {"id": "text-embedding-3-large", "owned_by": "openai"},
                    {"id": "whisper-1", "owned_by": "openai"},
                    {"id": "gpt-4o-mini", "owned_by": "openai"},
                ]
            },
        )
    )
    provider = OpenAIProvider(api_key="sk-test")
    models = await provider.list_models()
    ids = {m.id for m in models}
    assert ids == {"gpt-5", "gpt-4o-mini"}
    assert all(m.provider == ProviderName.OPENAI for m in models)


@pytest.mark.asyncio
async def test_openai_without_api_key_raises_authentication_error():
    provider = OpenAIProvider(api_key=None)
    with pytest.raises(AuthenticationError):
        await provider.list_models()


@pytest.mark.asyncio
@respx.mock
async def test_openai_401_raises_authentication_error():
    respx.get("https://api.openai.com/v1/models").mock(return_value=httpx.Response(401))
    provider = OpenAIProvider(api_key="sk-bad-key")
    with pytest.raises(AuthenticationError):
        await provider.list_models()


@pytest.mark.asyncio
@respx.mock
async def test_openai_complete_parses_tool_calls():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gpt-5",
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
    provider = OpenAIProvider(api_key="sk-test")
    result = await provider.complete(
        "gpt-5", [ChatMessage(role="user", content="hi")], []
    )
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {"path": "src/main.py"}


@pytest.mark.asyncio
@respx.mock
async def test_claude_list_models_normalizes():
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "claude-sonnet-5", "display_name": "Claude Sonnet 5"},
                    {"id": "claude-opus-4-8", "display_name": "Claude Opus 4.8"},
                ]
            },
        )
    )
    provider = ClaudeProvider(api_key="sk-ant-test")
    models = await provider.list_models()
    assert {m.id for m in models} == {"claude-sonnet-5", "claude-opus-4-8"}
    assert all(m.provider == ProviderName.CLAUDE for m in models)


@pytest.mark.asyncio
@respx.mock
async def test_claude_complete_splits_system_prompt():
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "claude-sonnet-5",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Looks fine."}],
            },
        )
    )
    provider = ClaudeProvider(api_key="sk-ant-test")
    messages = [
        ChatMessage(role="system", content="You are an auditor."),
        ChatMessage(role="user", content="Check this file."),
    ]
    result = await provider.complete("claude-sonnet-5", messages, [])
    assert result.text == "Looks fine."
    sent_body = route.calls[0].request.content
    import json as _json

    parsed = _json.loads(sent_body)
    assert parsed["system"] == "You are an auditor."
    assert all(m["role"] != "system" for m in parsed["messages"])


@pytest.mark.asyncio
@respx.mock
async def test_gemini_list_models_filters_non_generate_content():
    respx.get("https://generativelanguage.googleapis.com/v1beta/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-2.5-pro",
                        "displayName": "Gemini 2.5 Pro",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/embedding-001",
                        "displayName": "Embedding 001",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            },
        )
    )
    provider = GeminiProvider(api_key="AIzaTest")
    models = await provider.list_models()
    assert len(models) == 1
    assert models[0].id == "gemini-2.5-pro"


@pytest.mark.asyncio
@respx.mock
async def test_ollama_unreachable_raises_provider_unavailable():
    respx.get("http://localhost:11434/api/tags").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    provider = OllamaProvider()
    with pytest.raises(ProviderUnavailableError):
        await provider.list_models()


@pytest.mark.asyncio
@respx.mock
async def test_ollama_list_models_no_api_key_required():
    respx.get("http://localhost:11434/api/tags").mock(
        return_value=httpx.Response(
            200, json={"models": [{"name": "llama3.1:8b", "size": 123}]}
        )
    )
    provider = OllamaProvider()
    models = await provider.list_models()
    assert models[0].id == "llama3.1:8b"
    assert models[0].provider == ProviderName.OLLAMA


def test_registry_creates_correct_provider_classes():
    assert isinstance(create_provider(ProviderName.OPENAI, "k"), OpenAIProvider)
    assert isinstance(create_provider(ProviderName.CLAUDE, "k"), ClaudeProvider)
    assert isinstance(create_provider(ProviderName.GEMINI, "k"), GeminiProvider)
    assert isinstance(create_provider(ProviderName.OLLAMA, None), OllamaProvider)
