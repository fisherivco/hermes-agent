from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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


def _intermediate_result(state):
    envelope = {
        "state": state,
        "source_key": "src_test",
        "source_revision": "rev_test",
        "submission_path_absolute": f"/tmp/{state.lower()}.json",
        "next_action": "write the requested submission, then re-run",
    }
    return json.dumps({"output": json.dumps(envelope), "exit_code": 0, "error": None})


def _semantic_correction_result(*, state="SEMANTIC_CORRECTION_REQUIRED"):
    envelope = {
        "correction": {
            "accepted_response_committed": False,
            "code": "semantic_contract_invalid",
            "expected": {
                "additional_properties": False,
                "properties": {
                    "summary_text": {
                        "min_length": 1,
                        "type": "string",
                    },
                },
                "required": ["summary_text"],
                "type": "object",
            },
            "field_path": "$",
            "message": (
                "rev_7e1debb82977dfa4d08b.json has the wrong fields "
                "(extra=payload_type,schema)"
            ),
            "operation": "quick_summary",
            "request_id": "req_8763aabf9952ae979a9e163a",
            "run_id": "run_1957be144b0a7f805daf7b00",
            "schema": "draft-first.semantic-correction.v1",
            "submission_path": (
                "memory/ingest-state/semantic-exchange/submissions/quick_summary/"
                "src_fb99cede4f3550b4909f/rev_7e1debb82977dfa4d08b.json"
            ),
        },
        "error": (
            "SemanticCorrectionRequired: rev_7e1debb82977dfa4d08b.json has "
            "the wrong fields (extra=payload_type,schema)"
        ),
        "next_action": "replace_submission_payload_then_resume_same_public_request",
        "rc": 5,
        "schema": "draft-first.run-result.v1",
        "state": state,
    }
    return json.dumps({
        "output": json.dumps(envelope),
        "exit_code": 5,
        "error": None,
    })


def _material_blocked_result(message):
    envelope = {
        "state": "MATERIAL_BLOCKED_RETAINED",
        "material_report": {
            "state": "MATERIAL_BLOCKED_RETAINED",
            "source_key": "src_test",
            "draft_path": "memory/inbox/test.md",
            "counts": {
                "required": 1,
                "complete": 0,
                "pending_retryable": 0,
                "terminal": 1,
            },
            "blocked_components": ["image-1"],
            "reason": "required_material_is_terminal",
            "semantic_authoring_allowed": False,
            "next_action": "retain_material_state_and_stop",
        },
        "final_report_contract": {
            "version": "a054.material-blocked-report.v1.verbatim",
            "authoritative_field": "final_report_message",
            "sha256_field": "final_report_message_sha256",
            "encoding": "utf-8",
            "normalization": "none",
            "delivery": "exact_verbatim",
            "terminal_newline": "forbidden",
            "terminal_state": "MATERIAL_BLOCKED_RETAINED",
            "model_reauthoring_allowed": False,
            "required_fields": [
                "state",
                "source_key",
                "draft_path",
                "counts",
                "blocked_components",
                "reason",
                "semantic_authoring_allowed",
                "next_action",
            ],
            "counts_source": "durable_material_state",
            "success": False,
        },
        "final_report_message": message,
        "final_report_message_sha256": hashlib.sha256(
            message.encode()
        ).hexdigest(),
        "final_report_delivery_contract": {
            "version": "a054.material-blocked-report-delivery.v1",
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
            "terminal_state": "MATERIAL_BLOCKED_RETAINED",
        },
    }
    return json.dumps({"output": json.dumps(envelope), "exit_code": 4, "error": None})


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


def test_material_blocked_terminal_result_exits_before_second_model_call(
    monkeypatch,
):
    agent = _make_agent()
    call = _call()
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        AssertionError("second model request must not occur"),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(
            make_tool_result_message(
                "terminal",
                _material_blocked_result("Material settlement retained"),
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
    assert result["final_response"] == "Material settlement retained"
    assert result["final_delivery"]["message"] == "Material settlement retained"
    assert result["turn_exit_reason"] == "exact_delivery_success"
    assert result["completed"] is True
    assert result["failed"] is False


@pytest.mark.parametrize(
    "state",
    ["SUMMARY_REQUEST_READY", "SYNTHESIS_REQUEST_READY"],
)
def test_declared_intermediate_result_continues_with_current_tool_result(
    monkeypatch,
    state,
):
    agent = _make_agent()
    call = _call()
    tool_content = _intermediate_result(state)
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
    assert not any(
        message.get("role") == "assistant"
        and str(message.get("content", "")).startswith("Exact delivery refused:")
        for message in result["messages"]
    )


def test_live_semantic_correction_result_continues_with_current_tool_result(
    monkeypatch,
):
    agent = _make_agent()
    call = _call()
    tool_content = _semantic_correction_result()
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        _response(
            content="repaired semantic submission and resumed",
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
    assert result["final_response"] == "repaired semantic submission and resumed"
    assert result["turn_exit_reason"] != "exact_delivery_refused"
    assert "final_delivery" not in result
    assert not any(
        message.get("role") == "assistant"
        and str(message.get("content", "")).startswith("Exact delivery refused:")
        for message in result["messages"]
    )


def test_unknown_state_at_exit_five_refuses_without_model_fallback(monkeypatch):
    agent = _make_agent()
    call = _call()
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        AssertionError("exit code alone must not reach a second model request"),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(
            make_tool_result_message(
                "terminal",
                _semantic_correction_result(state="UNKNOWN_RETRY_READY"),
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
    assert result["turn_exit_reason"] == "exact_delivery_refused"
    assert result["final_response"].startswith("Exact delivery refused:")
    assert result["failed"] is True


def test_semantic_correction_with_final_report_fields_refuses(monkeypatch):
    agent = _make_agent()
    call = _call()
    correction = json.loads(_semantic_correction_result())
    envelope = json.loads(correction["output"])
    envelope["final_report_message"] = "must not be accepted"
    correction["output"] = json.dumps(envelope)
    tool_content = json.dumps(correction)
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        AssertionError("report-bearing correction must not reach a second model request"),
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

    assert agent.client.chat.completions.create.call_count == 1
    assert result["turn_exit_reason"] == "exact_delivery_refused"
    assert result["final_response"].startswith("Exact delivery refused:")
    assert result["failed"] is True


def test_non_declared_launcher_state_still_refuses_without_model_fallback(
    monkeypatch,
):
    agent = _make_agent()
    call = _call()
    agent.client.chat.completions.create.side_effect = [
        _response(tool_calls=[call]),
        AssertionError("non-declared state must not reach a second model request"),
    ]

    def execute(_assistant, messages, _task_id, api_call_count=0):
        messages.append(
            make_tool_result_message(
                "terminal",
                _intermediate_result("PAIR_READY"),
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
    assert result["turn_exit_reason"] == "exact_delivery_refused"
    assert result["final_response"].startswith("Exact delivery refused:")
    assert result["failed"] is True


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
