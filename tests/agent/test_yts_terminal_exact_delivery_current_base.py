"""YTS qualification for current-turn terminal exact delivery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.final_delivery import (
    FinalDeliveryError,
    is_terminal_final_delivery_candidate,
    parse_declared_intermediate_state,
    parse_terminal_final_delivery,
)


YTS_WORKFLOW = "$HOME/fisher/shared-state/skills-hub/skills/yts/scripts/yts_workflow.py"
YTS_WORKFLOW_ABSOLUTE = str(
    Path.home() / "fisher/shared-state/skills-hub/skills/yts/scripts/yts_workflow.py"
)


def _contract() -> dict:
    return {
        "version": "yts.origin-report.v1.verbatim",
        "authoritative_field": "final_report_message",
        "sha256_field": "final_report_message_sha256",
        "encoding": "utf-8",
        "normalization": "none",
        "delivery": "exact_verbatim",
        "terminal_newline": "forbidden",
        "terminal_states": [
            "VERIFIED",
            "DUPLICATE_VERIFIED",
            "NO_TRANSCRIPT",
            "CAPTURE_FAILED",
        ],
        "model_reauthoring_allowed": False,
        "source_grounded": True,
        "process_only_rejected": True,
    }


def _delivery_contract() -> dict:
    return {
        "version": "yts.origin-report-delivery.v1",
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
    }


def _envelope(state: str, message: str) -> dict:
    return {
        "state": state,
        "final_report_contract": _contract(),
        "final_report_message": message,
        "final_report_message_sha256": hashlib.sha256(
            message.encode("utf-8")
        ).hexdigest(),
        "final_report_delivery_contract": _delivery_contract(),
    }


def _pair(
    *,
    command: str,
    envelope: dict,
    exit_code: int,
) -> tuple[SimpleNamespace, dict]:
    call = SimpleNamespace(
        id="call-yts-1",
        function=SimpleNamespace(
            name="terminal",
            arguments=json.dumps({"command": command, "background": False}),
        ),
    )
    result = {
        "role": "tool",
        "name": "terminal",
        "tool_call_id": "call-yts-1",
        "content": json.dumps({
            "output": json.dumps(envelope, ensure_ascii=False),
            "exit_code": exit_code,
            "error": None,
        }),
    }
    return call, result


def _no_redaction(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )


def test_yts_start_analysis_ready_is_a_declared_continuation(monkeypatch) -> None:
    command = (
        f'python3 "{YTS_WORKFLOW}" start '
        '--url "https://youtu.be/abc123ABC12" --fisher-root "$HOME/fisher"'
    )
    call, result = _pair(
        command=command,
        envelope={"state": "ANALYSIS_REQUEST_READY", "next_action": "write_submission"},
        exit_code=0,
    )
    _no_redaction(monkeypatch)

    assert is_terminal_final_delivery_candidate([call]) is True
    assert (
        parse_declared_intermediate_state([call], [result]) == "ANALYSIS_REQUEST_READY"
    )


def test_yts_no_transcript_exit_four_is_exact_without_model_reauthoring(
    monkeypatch,
) -> None:
    message = (
        "NO_TRANSCRIPT: https://youtu.be/abc123ABC12 has no transcript; "
        "unable to fetch."
    )
    command = (
        f'python3 "{YTS_WORKFLOW}" start '
        '--url "https://youtu.be/abc123ABC12" --fisher-root "$HOME/fisher"'
    )
    call, result = _pair(
        command=command,
        envelope=_envelope("NO_TRANSCRIPT", message),
        exit_code=4,
    )
    _no_redaction(monkeypatch)

    delivery = parse_terminal_final_delivery([call], [result])

    assert delivery.message == message
    assert delivery.sha256 == hashlib.sha256(message.encode()).hexdigest()


@pytest.mark.parametrize("state", ["VERIFIED", "DUPLICATE_VERIFIED"])
def test_yts_finalize_success_is_exact(monkeypatch, state: str) -> None:
    message = "影片摘要\n\n一句話摘要\n\n可驗證的精簡內容"
    command = (
        f'python3 "{YTS_WORKFLOW_ABSOLUTE}" finalize '
        '--run-dir "/tmp/yts-run" --repository "fisherivco/fisher"'
    )
    call, result = _pair(
        command=command,
        envelope=_envelope(state, message),
        exit_code=0,
    )
    _no_redaction(monkeypatch)

    delivery = parse_terminal_final_delivery([call], [result])

    assert delivery.message == message


@pytest.mark.parametrize(
    ("state", "exit_code"),
    [("NO_TRANSCRIPT", 0), ("VERIFIED", 4), ("CAPTURE_FAILED", 4)],
)
def test_yts_terminal_state_and_exit_code_must_match(
    monkeypatch,
    state: str,
    exit_code: int,
) -> None:
    subcommand = "finalize" if state == "VERIFIED" else "start"
    command = (
        f'python3 "{YTS_WORKFLOW}" {subcommand} --url "https://youtu.be/abc123ABC12"'
    )
    call, result = _pair(
        command=command,
        envelope=_envelope(state, "bounded response"),
        exit_code=exit_code,
    )
    _no_redaction(monkeypatch)

    with pytest.raises(FinalDeliveryError):
        parse_terminal_final_delivery([call], [result])


def test_untrusted_python_script_is_not_a_candidate() -> None:
    call, _result = _pair(
        command='python3 "/tmp/yts_workflow.py" finalize --run-dir "/tmp/run"',
        envelope=_envelope("VERIFIED", "bounded response"),
        exit_code=0,
    )

    assert is_terminal_final_delivery_candidate([call]) is False


def test_yts_semantic_input_is_not_a_terminal_delivery_candidate() -> None:
    call, _result = _pair(
        command=(f'python3 "{YTS_WORKFLOW}" semantic-input --run-dir "/tmp/yts-run"'),
        envelope={"state": "READ_ONLY_SEMANTIC_INPUT"},
        exit_code=0,
    )

    assert is_terminal_final_delivery_candidate([call]) is False
