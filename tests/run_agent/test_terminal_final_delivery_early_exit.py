from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.tool_dispatch_helpers import make_tool_result_message
from run_agent import AIAgent


LAUNCHER = "/Users/fisherivco/fisher/shared-state/skills-hub/skills/ingest/scripts/draft-first-run"


def _make_agent():
    home = Path(tempfile.mkdtemp(prefix="hermes-exact-test-"))
    (home / "logs").mkdir(parents=True, exist_ok=True)
    tool_defs = [{"type": "function", "function": {"name": "terminal", "description": "terminal", "parameters": {"type": "object", "properties": {}}}}]
    with (
        patch("run_agent.get_tool_definitions", return_value=tool_defs),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
        patch("run_agent._hermes_home", home),
        patch("agent.model_metadata.fetch_model_metadata", return_value={}),
    ):
        agent = AIAgent(api_key="test", base_url="https://example.test/v1", quiet_mode=True, skip_context_files=True, skip_memory=True)
    agent.client = MagicMock()
    agent._cached_system_prompt = "You are helpful."
    agent._use_prompt_caching = False
    agent.compression_enabled = False
    agent.save_trajectories = False
    return agent


def _response(*, tool_calls=None, content="", finish_reason="tool_calls"):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)], model="test/model", usage=None)


def _call():
    return SimpleNamespace(id="call-1", type="function", function=SimpleNamespace(name="terminal", arguments=json.dumps({"command": f"{LAUNCHER} https://example.test/source"})))


def _terminal_result(message):
    envelope = {
        "state": "VERIFIED",
        "final_report_contract": {
            "version": "a054.final-report.v2.verbatim",
            "authoritative_field": "final_report_message",
            "sha256_field": "final_report_message_sha256",
            "encoding": "utf-8",
            "normalization": "none",
            "delivery": "exact_verbatim",
            "terminal_newline": "forbidden",
            "terminal_state": "VERIFIED",
            "model_reauthoring_allowed": False,
            "required_order": [
                "Knowledge headline", "Core insight", "Key insights",
                "Value verdict", "Allen AI OS / harness mapping", "IVCO lens",
                "Caveats / limits", "Useful next actions (Do Now)", "Defer",
                "Verification receipt",
            ],
            "minimum_key_insights": 3,
            "receipt_last": True,
            "source_grounded": True,
            "process_only_rejected": True,
            "additive_only": True,
            "success": True,
        },
        "final_report_message": message,
        "final_report_message_sha256": hashlib.sha256(message.encode()).hexdigest(),
        "final_report_delivery_contract": {
            "version": "a054.final-report-delivery.v2",
            "authoritative_field": "final_report_message",
            "sha256_field": "final_report_message_sha256",
            "encoding": "utf-8",
            "normalization": "none",
            "mode": "exact_verbatim",
            "preamble_allowed": False,
            "suffix_allowed": False,
            "translation_allowed": False,
            "reconstruction_allowed": False,
            "terminal_newline": "forbidden",
        },
    }
    return json.dumps({"output": json.dumps(envelope), "exit_code": 0, "error": None})


def test_qualifying_terminal_result_exits_before_second_model_call(monkeypatch):
    agent = _make_agent()
    call = _call()
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        AssertionError("second model request must not occur"),
    ]
    persisted = []
    cleanup = MagicMock()
    trajectory = MagicMock()

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(make_tool_result_message("terminal", _terminal_result("exact payload"), "call-1"))

    monkeypatch.setattr("agent.final_delivery.redact_terminal_output", lambda text, command, force=False: text)
    with (
        patch.object(agent, "_execute_tool_calls", side_effect=execute),
        patch.object(agent, "_persist_session", side_effect=lambda messages, history=None: persisted.append(list(messages))),
        patch.object(agent, "_save_trajectory", trajectory),
        patch.object(agent, "_cleanup_task_resources", cleanup),
    ):
        result = agent.run_conversation("ingest source")

    assert agent.client.chat.completions.create.call_count == 1
    assert result["final_response"] == "exact payload"
    assert result["final_delivery"]["message"] == "exact payload"
    assert result["messages"][-1] == {"role": "assistant", "content": "exact payload"}
    assert persisted and persisted[-1][-1] == {"role": "assistant", "content": "exact payload"}
    assert result["turn_exit_reason"] == "exact_delivery_success"
    assert result["completed"] is True
    assert result["failed"] is False
    assert cleanup.call_count == 1
    assert trajectory.call_count == 1
    assert agent._stream_callback is None


def test_exact_delivery_refuses_when_final_persistence_fails(monkeypatch):
    agent = _make_agent()
    call = _call()
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        AssertionError("persistence failure must not reach a second model request"),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(make_tool_result_message("terminal", _terminal_result("exact payload"), "call-1"))

    monkeypatch.setattr("agent.final_delivery.redact_terminal_output", lambda text, command, force=False: text)
    with (
        patch.object(agent, "_execute_tool_calls", side_effect=execute),
        patch.object(agent, "_persist_session", side_effect=RuntimeError("disk unavailable")),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation("ingest source")

    assert agent.client.chat.completions.create.call_count == 1
    assert "final_delivery" not in result
    assert result["completed"] is False
    assert result["failed"] is True
    assert result["turn_exit_reason"] == "exact_delivery_refused"
    assert result["final_response"] == "Exact delivery refused: the exact response could not be durably persisted."
    assert any(error.startswith("persist_session:") for error in result["cleanup_errors"])


def test_nonqualifying_terminal_result_continues_to_model():
    agent = _make_agent()
    call = _call()
    call.function.arguments = json.dumps({"command": "printf ordinary"})
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        _response(content="normal fallback", tool_calls=None, finish_reason="stop"),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(make_tool_result_message("terminal", json.dumps({"output": "ordinary", "exit_code": 0, "error": None}), "call-1"))

    with (
        patch.object(agent, "_execute_tool_calls", side_effect=execute),
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation("run ordinary command")

    assert agent.client.chat.completions.create.call_count == 2
    assert result["final_response"] == "normal fallback"
    assert "final_delivery" not in result


def test_allowlisted_contract_failure_is_visible_without_model_fallback(monkeypatch):
    agent = _make_agent()
    call = _call()
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        AssertionError("contract failure must not reach a second model request"),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(make_tool_result_message(
            "terminal",
            json.dumps({"output": "not an exact envelope", "exit_code": 0, "error": None}),
            "call-1",
        ))

    monkeypatch.setattr("agent.final_delivery.redact_terminal_output", lambda text, command, force=False: text)
    cleanup = MagicMock()
    trajectory = MagicMock()
    with (
        patch.object(agent, "_execute_tool_calls", side_effect=execute),
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory", trajectory),
        patch.object(agent, "_cleanup_task_resources", cleanup),
    ):
        result = agent.run_conversation("ingest source")

    assert agent.client.chat.completions.create.call_count == 1
    assert result["completed"] is False
    assert result["failed"] is True
    assert result["turn_exit_reason"] == "exact_delivery_refused"
    assert result["final_response"].startswith("Exact delivery refused:")
    assert result["messages"][-1]["content"] == result["final_response"]
    assert cleanup.call_count == 1
    assert trajectory.call_count == 1


def _assert_candidate_attempt_refuses_without_second_model(monkeypatch, calls):
    agent = _make_agent()
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=calls),
        AssertionError("candidate invariant failure must not reach a second model request"),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        for call in calls:
            messages.append(make_tool_result_message(
                "terminal", _terminal_result("exact payload"), call.id,
            ))

    monkeypatch.setattr("agent.final_delivery.redact_terminal_output", lambda text, command, force=False: text)
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


def test_background_canonical_launcher_attempt_refuses_without_model_fallback(monkeypatch):
    call = _call()
    call.function.arguments = json.dumps({
        "command": f"{LAUNCHER} https://example.test/source",
        "background": True,
    })
    _assert_candidate_attempt_refuses_without_second_model(monkeypatch, [call])


def test_canonical_launcher_plus_second_tool_refuses_without_model_fallback(monkeypatch):
    other = SimpleNamespace(
        id="call-2", type="function",
        function=SimpleNamespace(name="terminal", arguments=json.dumps({"command": "printf ordinary"})),
    )
    _assert_candidate_attempt_refuses_without_second_model(monkeypatch, [_call(), other])


def test_composed_canonical_launcher_attempt_refuses_without_model_fallback(monkeypatch):
    call = _call()
    call.function.arguments = json.dumps({
        "command": f"{LAUNCHER} https://example.test/source $(printf nope)",
    })
    _assert_candidate_attempt_refuses_without_second_model(monkeypatch, [call])


def test_ordinary_nonlauncher_two_call_turn_still_reaches_second_model():
    agent = _make_agent()
    calls = []
    for index in (1, 2):
        calls.append(SimpleNamespace(
            id=f"call-{index}", type="function",
            function=SimpleNamespace(name="terminal", arguments=json.dumps({"command": f"printf ordinary-{index}"})),
        ))
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=calls),
        _response(content="ordinary final", tool_calls=None, finish_reason="stop"),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        for call in calls:
            messages.append(make_tool_result_message("terminal", "ordinary", call.id))

    with (
        patch.object(agent, "_execute_tool_calls", side_effect=execute),
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation("ordinary commands")
    assert agent.client.chat.completions.create.call_count == 2
    assert result["final_response"] == "ordinary final"
