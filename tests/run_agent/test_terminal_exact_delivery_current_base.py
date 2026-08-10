"""Conversation-loop coverage for terminal-owned exact delivery."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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


def _continuation_result(state: str, exit_code: int) -> str:
    envelope = {
        "state": state,
        "source_key": "src_test",
        "source_revision": "rev_test",
        "submission_path_absolute": f"/tmp/{state.lower()}.json",
        "next_action": "resume_same_public_request",
    }
    return json.dumps(
        {
            "output": json.dumps(envelope),
            "exit_code": exit_code,
            "error": None,
        }
    )


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


@pytest.mark.parametrize(
    ("state", "exit_code"),
    [
        ("SUMMARY_REQUEST_READY", 0),
        ("SYNTHESIS_REQUEST_READY", 0),
        ("SEMANTIC_CORRECTION_REQUIRED", 5),
    ],
)
def test_declared_ingest_continuation_returns_to_model_loop(
    monkeypatch,
    tmp_path,
    state: str,
    exit_code: int,
) -> None:
    agent = _make_agent(tmp_path)
    call = _call()
    tool_content = _continuation_result(state, exit_code)
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        _response(
            content=f"continued after {state}",
            tool_calls=None,
            finish_reason="stop",
        ),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(
            make_tool_result_message("terminal", tool_content, "call-1")
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

    assert agent.client.chat.completions.create.call_count == 2
    second_messages = (
        agent.client.chat.completions.create.call_args_list[1].kwargs["messages"]
    )
    assert any(
        message.get("role") == "tool"
        and message.get("tool_call_id") == "call-1"
        and message.get("content") == tool_content
        for message in second_messages
    )
    assert result["final_response"] == f"continued after {state}"
    assert result["turn_exit_reason"] != "exact_delivery_refused"
    assert "final_delivery" not in result


@pytest.mark.parametrize(
    ("state", "exit_code"),
    [
        ("UNKNOWN_RETRY_READY", 5),
        ("SUMMARY_REQUEST_READY", 5),
        ("SEMANTIC_CORRECTION_REQUIRED", 0),
    ],
)
def test_undeclared_ingest_continuation_pair_still_refuses(
    monkeypatch,
    tmp_path,
    state: str,
    exit_code: int,
) -> None:
    agent = _make_agent(tmp_path)
    call = _call()
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        AssertionError("an undeclared pair must not reach model fallback"),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(
            make_tool_result_message(
                "terminal",
                _continuation_result(state, exit_code),
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


def test_report_bearing_ingest_continuation_still_refuses(
    monkeypatch,
    tmp_path,
) -> None:
    agent = _make_agent(tmp_path)
    call = _call()
    wrapper = json.loads(_continuation_result("SUMMARY_REQUEST_READY", 0))
    envelope = json.loads(wrapper["output"])
    envelope["final_report_message"] = "must not bypass terminal qualification"
    wrapper["output"] = json.dumps(envelope)
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        AssertionError("a report-bearing midstate must not reach model fallback"),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(
            make_tool_result_message(
                "terminal",
                json.dumps(wrapper),
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


def test_terminal_report_before_continuation_line_still_delivers_exactly(
    monkeypatch,
    tmp_path,
) -> None:
    agent = _make_agent(tmp_path)
    call = _call()
    wrapper = json.loads(_terminal_result("must remain exact"))
    continuation = json.loads(
        _continuation_result("SUMMARY_REQUEST_READY", 0)
    )
    wrapper["output"] = "\n".join(
        (wrapper["output"], continuation["output"])
    )
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        _response(
            content="model rewrote terminal report",
            tool_calls=None,
            finish_reason="stop",
        ),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(
            make_tool_result_message(
                "terminal",
                json.dumps(wrapper),
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
    assert result["failed"] is False
    assert result["turn_exit_reason"] == "exact_delivery_success"
    assert result["final_response"] == "must remain exact"
    assert result["final_delivery"]["message"] == "must remain exact"


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
