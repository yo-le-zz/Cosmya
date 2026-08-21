import sys
import types

import pytest

from cosmya.ai.models import ChatMessage, CompletionResult, ToolCall
from cosmya.ai.provider import AIProvider
from cosmya.config.models import ProviderName


class ScriptedProvider(AIProvider):
    """A fake provider that returns a scripted sequence of completions."""

    name = ProviderName.OPENAI

    def __init__(self, responses: list[CompletionResult]) -> None:
        super().__init__(api_key="fake")
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    async def list_models(self):
        return []

    async def complete(self, model_id, messages, tools):
        self.calls.append(list(messages))
        return self._responses.pop(0)


@pytest.fixture
def fake_native(monkeypatch):
    fake_module = types.ModuleType("cosmya._native")
    fake_module.tree = lambda root, path, max_depth=5: {"success": True, "tree": "a.py"}
    fake_module.read_file = lambda root, path: {"success": True, "content": "x = 1"}
    monkeypatch.setitem(sys.modules, "cosmya._native", fake_module)
    import cosmya.agent.tools as tools_module

    monkeypatch.setattr(tools_module, "_native", fake_module)
    monkeypatch.setattr(tools_module, "_NATIVE_AVAILABLE", True)
    yield fake_module


VALID_FINAL_JSON = (
    '{"summary": {"score": 90, "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}, '
    '"findings": []}'
)


@pytest.mark.asyncio
async def test_agent_loop_executes_tool_calls_then_returns_result(fake_native):
    from cosmya.agent.engine import run_audit

    responses = [
        CompletionResult(
            tool_calls=[ToolCall(id="c1", name="tree", arguments={"path": "."})]
        ),
        CompletionResult(text=VALID_FINAL_JSON),
    ]
    provider = ScriptedProvider(responses)

    result = await run_audit(
        provider=provider,
        model_id="fake-model",
        project_root="/tmp/project",
        project_label="/tmp/project",
        custom_instructions="",
    )

    assert result.audit.summary.score == 90
    assert result.turns_used == 2
    # The tool result must have been fed back into the conversation.
    last_call_messages = provider.calls[-1]
    assert any(m.role == "tool" for m in last_call_messages)


@pytest.mark.asyncio
async def test_agent_loop_recovers_from_one_bad_json_response(fake_native):
    from cosmya.agent.engine import run_audit

    responses = [
        CompletionResult(text="not valid json at all"),
        CompletionResult(text=VALID_FINAL_JSON),
    ]
    provider = ScriptedProvider(responses)

    result = await run_audit(
        provider=provider,
        model_id="fake-model",
        project_root="/tmp/project",
        project_label="/tmp/project",
        custom_instructions="",
    )
    assert result.audit.summary.score == 90


@pytest.mark.asyncio
async def test_agent_loop_gives_up_after_max_correction_attempts(fake_native):
    from cosmya.agent.engine import run_audit
    from cosmya.audit.schema import InvalidAuditResponseError

    # Always return invalid JSON -- should eventually raise rather than loop forever.
    responses = [CompletionResult(text="still not json") for _ in range(10)]
    provider = ScriptedProvider(responses)

    with pytest.raises(InvalidAuditResponseError):
        await run_audit(
            provider=provider,
            model_id="fake-model",
            project_root="/tmp/project",
            project_label="/tmp/project",
            custom_instructions="",
        )


@pytest.mark.asyncio
async def test_user_preferences_are_injected_as_data_not_instructions(fake_native):
    from cosmya.agent.engine import run_audit

    responses = [CompletionResult(text=VALID_FINAL_JSON)]
    provider = ScriptedProvider(responses)

    await run_audit(
        provider=provider,
        model_id="fake-model",
        project_root="/tmp/project",
        project_label="/tmp/project",
        custom_instructions="Be extremely strict about security.",
    )
    system_message = provider.calls[0][0]
    assert system_message.role == "system"
    assert "Be extremely strict about security." in system_message.content
    assert "User preferences" in system_message.content
