"""Conversation-loop coverage for terminal-owned exact delivery."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.final_delivery import (
    VERIFIED_DELIVERY_CONTRACT,
    VERIFIED_FINAL_REPORT_CONTRACT,
)
from agent.tool_dispatch_helpers import make_tool_result_message
from run_agent import AIAgent


LAUNCHER = "$HOME/fisher/shared-state/skills-hub/skills/ingest/scripts/draft-first-run"


def _make_agent(home: Path) -> AIAgent:
    (home / "logs").mkdir(parents=True, exist_ok=True)
    terminal_definition = [
        {
            "type": "function",
            "function": {
                "name": "terminal",
                "description": "terminal",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    with (
        patch("run_agent.get_tool_definitions", return_value=terminal_definition),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
        patch("run_agent._hermes_home", home),
        patch("agent.model_metadata.fetch_model_metadata", return_value={}),
    ):
        agent = AIAgent(
            api_key="test",
            base_url="https://example.test/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
    agent.client = MagicMock()
    agent._cached_system_prompt = "You are helpful."
    agent._use_prompt_caching = False
    agent.compression_enabled = False
    agent.save_trajectories = False
    agent._flush_messages_to_session_db = MagicMock(return_value=True)
    return agent


def _response(*, tool_calls=None, content="", finish_reason="tool_calls"):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        model="test/model",
        usage=None,
    )


def _call(command: str | None = None):
    return SimpleNamespace(
        id="call-1",
        type="function",
        function=SimpleNamespace(
            name="terminal",
            arguments=json.dumps(
                {
                    "command": command
                    or f'"{LAUNCHER}" "https://example.test/source"'
                }
            ),
        ),
    )


def _terminal_result(message: str) -> str:
    envelope = {
        "state": "VERIFIED",
        "final_report_contract": deepcopy(VERIFIED_FINAL_REPORT_CONTRACT),
        "final_report_delivery_contract": deepcopy(VERIFIED_DELIVERY_CONTRACT),
        "final_report_message": message,
        "final_report_message_sha256": hashlib.sha256(
            message.encode("utf-8")
        ).hexdigest(),
    }
    output = "\n".join(
        (
            json.dumps({"state": "SUMMARY_READY"}),
            json.dumps(envelope),
        )
    )
    return json.dumps({"output": output, "exit_code": 0, "error": None})


def test_qualifying_terminal_result_exits_before_model_reauthors_bytes(
    monkeypatch,
    tmp_path,
) -> None:
    agent = _make_agent(tmp_path)
    call = _call()
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        AssertionError("a second model request must not re-author exact bytes"),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(
            make_tool_result_message(
                "terminal",
                _terminal_result("exact payload 摘要"),
                "call-1",
            )
        )

    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )
    with (
        patch.object(agent, "_execute_tool_calls", side_effect=execute),
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation("ingest source")

    assert agent.client.chat.completions.create.call_count == 1
    assert result["final_response"] == "exact payload 摘要"
    assert result["final_delivery"]["message"] == "exact payload 摘要"
    assert result["messages"][-1] == {
        "role": "assistant",
        "content": "exact payload 摘要",
    }
    assert result["turn_exit_reason"] == "exact_delivery_success"


def test_historical_duplicate_call_id_cannot_enter_current_turn(
    monkeypatch,
    tmp_path,
) -> None:
    agent = _make_agent(tmp_path)
    call = _call()
    agent.client.chat.completions.create.return_value = _response(tool_calls=[call])
    history = [
        {"role": "user", "content": "prior request"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "terminal",
                        "arguments": json.dumps(
                            {"command": f'"{LAUNCHER}" "https://old.test/source"'}
                        ),
                    },
                }
            ],
        },
        make_tool_result_message(
            "terminal",
            _terminal_result("stale payload"),
            "call-1",
        ),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(
            make_tool_result_message(
                "terminal",
                _terminal_result("current payload"),
                "call-1",
            )
        )

    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )
    with (
        patch.object(agent, "_execute_tool_calls", side_effect=execute),
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation(
            "ingest current source",
            conversation_history=history,
        )

    assert result["final_response"] == "current payload"
    assert result["final_delivery"]["message"] == "current payload"
    assert result["turn_exit_reason"] == "exact_delivery_success"


def test_nonqualifying_terminal_command_keeps_ordinary_model_path(tmp_path) -> None:
    agent = _make_agent(tmp_path)
    call = _call("printf ordinary")
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        _response(
            content="ordinary final",
            tool_calls=None,
            finish_reason="stop",
        ),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(
            make_tool_result_message(
                "terminal",
                json.dumps({"output": "ordinary", "exit_code": 0, "error": None}),
                "call-1",
            )
        )

    with (
        patch.object(agent, "_execute_tool_calls", side_effect=execute),
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation("run ordinary command")

    assert agent.client.chat.completions.create.call_count == 2
    assert result["final_response"] == "ordinary final"
    assert "final_delivery" not in result


def test_candidate_contract_failure_refuses_without_model_fallback(
    monkeypatch,
    tmp_path,
) -> None:
    agent = _make_agent(tmp_path)
    call = _call()
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        AssertionError("a rejected candidate must not reach model fallback"),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(
            make_tool_result_message(
                "terminal",
                json.dumps(
                    {"output": "not an exact envelope", "exit_code": 0, "error": None}
                ),
                "call-1",
            )
        )

    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )
    with (
        patch.object(agent, "_execute_tool_calls", side_effect=execute),
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation("ingest source")

    assert agent.client.chat.completions.create.call_count == 1
    assert result["failed"] is True
    assert result["turn_exit_reason"] == "exact_delivery_refused"
    assert result["final_response"].startswith("Exact delivery refused:")
    assert "final_delivery" not in result


def test_exact_delivery_requires_durable_final_persistence(
    monkeypatch,
    tmp_path,
) -> None:
    agent = _make_agent(tmp_path)
    call = _call()
    agent.client.chat.completions.create.return_value = _response(tool_calls=[call])

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(
            make_tool_result_message(
                "terminal",
                _terminal_result("exact payload"),
                "call-1",
            )
        )

    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )
    with (
        patch.object(agent, "_execute_tool_calls", side_effect=execute),
        patch.object(
            agent,
            "_persist_session",
            side_effect=RuntimeError("disk unavailable"),
        ),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation("ingest source")

    assert agent.client.chat.completions.create.call_count == 1
    assert result["failed"] is True
    assert result["turn_exit_reason"] == "exact_delivery_refused"
    assert "final_delivery" not in result
    assert result["final_response"] == (
        "Exact delivery refused: the exact response could not be durably persisted."
    )
