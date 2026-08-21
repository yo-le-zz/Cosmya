"""The agent loop: drives the model through repeated tool calls until it
produces a final validated :class:`AuditResult`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from cosmya.agent.prompts import (
    SYSTEM_PROMPT,
    build_initial_user_request,
    build_user_preferences_block,
)
from cosmya.agent.tools import TOOL_DEFINITIONS, ToolExecutor
from cosmya.ai.models import ChatMessage, ToolResultMessage
from cosmya.ai.provider import AIProvider
from cosmya.audit.schema import (
    AuditResult,
    InvalidAuditResponseError,
    parse_audit_result,
)

_MAX_AGENT_TURNS = 40
_MAX_JSON_CORRECTION_ATTEMPTS = 2

ProgressCallback = Callable[[str], None]


@dataclass
class AgentRunResult:
    audit: AuditResult
    turns_used: int
    transcript: list[ChatMessage] = field(default_factory=list)


class AgentTurnLimitError(Exception):
    """Raised when the model exhausts the allowed number of tool-call turns
    without producing a valid final JSON result."""


async def run_audit(
    provider: AIProvider,
    model_id: str,
    project_root: str,
    project_label: str,
    custom_instructions: str,
    on_progress: ProgressCallback | None = None,
) -> AgentRunResult:
    """Run the full agent loop for one audit and return a validated result."""

    def report(message: str) -> None:
        if on_progress:
            on_progress(message)

    executor = ToolExecutor(project_root)

    preferences_block = build_user_preferences_block(custom_instructions)
    system_content = SYSTEM_PROMPT
    if preferences_block:
        system_content = f"{SYSTEM_PROMPT}\n{preferences_block}"

    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=system_content),
        ChatMessage(role="user", content=build_initial_user_request(project_label)),
    ]

    correction_attempts = 0

    for turn in range(1, _MAX_AGENT_TURNS + 1):
        report(f"Turn {turn}: waiting on model")
        result = await provider.complete(model_id, messages, TOOL_DEFINITIONS)

        if result.tool_calls:
            messages.append(
                ChatMessage(
                    role="assistant", content=result.text, tool_calls=result.tool_calls
                )
            )
            for call in result.tool_calls:
                report(f"Tool call: {call.name}({call.arguments})")
                tool_output = executor.execute(call.name, call.arguments)
                messages.append(
                    ChatMessage(
                        role="tool",
                        tool_result=ToolResultMessage(
                            tool_call_id=call.id, name=call.name, content=tool_output
                        ),
                    )
                )
            continue

        # No tool calls: the model believes it is done. Try to parse its
        # final answer as the required JSON schema.
        if result.text is None:
            messages.append(
                ChatMessage(
                    role="user",
                    content=(
                        "Your previous response had no content and no tool "
                        "calls. Please either call a tool or return your "
                        "final JSON report."
                    ),
                )
            )
            continue

        try:
            audit = parse_audit_result(result.text)
        except InvalidAuditResponseError as exc:
            correction_attempts += 1
            if correction_attempts > _MAX_JSON_CORRECTION_ATTEMPTS:
                raise InvalidAuditResponseError(
                    "The model repeatedly failed to produce valid schema-"
                    f"conforming JSON after {correction_attempts - 1} correction "
                    f"attempts. Last error: {exc}"
                ) from exc
            messages.append(ChatMessage(role="assistant", content=result.text))
            messages.append(
                ChatMessage(
                    role="user",
                    content=(
                        "Your final answer did not match the required JSON "
                        f"schema: {exc}. Respond again with ONLY the corrected "
                        "JSON object matching the schema, with no other text."
                    ),
                )
            )
            continue

        return AgentRunResult(audit=audit, turns_used=turn, transcript=messages)

    raise AgentTurnLimitError(
        f"The model did not produce a valid audit result within "
        f"{_MAX_AGENT_TURNS} turns."
    )
