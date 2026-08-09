"""Fail-closed qualification for current-turn terminal exact delivery."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from agent.final_delivery import (
    FinalDeliveryError,
    is_terminal_final_delivery_candidate,
    parse_terminal_final_delivery,
)


LAUNCHER = "$HOME/fisher/shared-state/skills-hub/skills/ingest/scripts/draft-first-run"


def _envelope(message: str = "## Exact report") -> dict:
    return {
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
                "Knowledge headline",
                "Core insight",
                "Key insights",
                "Value verdict",
                "Allen AI OS / harness mapping",
                "IVCO lens",
                "Caveats / limits",
                "Useful next actions (Do Now)",
                "Defer",
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
        "final_report_message_sha256": hashlib.sha256(
            message.encode("utf-8")
        ).hexdigest(),
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


def _pair(
    *,
    envelope: dict | None = None,
    command: str | None = None,
    background: bool = False,
) -> tuple[SimpleNamespace, dict]:
    call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="terminal",
            arguments=json.dumps(
                {
                    "command": command
                    or f'"{LAUNCHER}" "https://example.test/source"',
                    "background": background,
                }
            ),
        ),
    )
    summary = {"state": "SUMMARY_READY", "next_action": "continue"}
    output = "\n".join(
        (json.dumps(summary), json.dumps(envelope or _envelope()))
    )
    result = {
        "role": "tool",
        "name": "terminal",
        "tool_call_id": "call-1",
        "content": json.dumps(
            {"output": output, "exit_code": 0, "error": None}
        ),
    }
    return call, result


def test_accepts_observed_multistage_current_turn_shape(monkeypatch) -> None:
    call, result = _pair()
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    delivery = parse_terminal_final_delivery([call], [result])

    assert delivery.message == "## Exact report"
    assert delivery.sha256 == hashlib.sha256(delivery.message.encode()).hexdigest()


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda call, result: setattr(call.function, "name", "read_file"), "tool_name"),
        (lambda call, result: result.update(tool_call_id="stale-call"), "current_turn"),
        (
            lambda call, result: setattr(
                call.function,
                "arguments",
                json.dumps(
                    {
                        "command": f'"{LAUNCHER}" "https://example.test/source"',
                        "background": True,
                    }
                ),
            ),
            "background",
        ),
    ],
)
def test_rejects_nonterminal_stale_or_background_result(
    monkeypatch,
    mutate,
    reason: str,
) -> None:
    call, result = _pair()
    mutate(call, result)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match=reason):
        parse_terminal_final_delivery([call], [result])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda envelope: envelope.update(final_report_message_sha256="0" * 64),
        lambda envelope: envelope["final_report_delivery_contract"].update(
            preamble_allowed=True
        ),
        lambda envelope: envelope.update(state="PAIR_READY"),
        lambda envelope: envelope.update(final_report_message="ends with newline\n"),
    ],
)
def test_rejects_altered_contract_or_bytes(monkeypatch, mutate) -> None:
    envelope = _envelope()
    mutate(envelope)
    call, result = _pair(envelope=envelope)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError):
        parse_terminal_final_delivery([call], [result])


def test_rejects_forced_redaction_change(monkeypatch) -> None:
    call, result = _pair()
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text.replace("Exact", "[REDACTED]"),
    )

    with pytest.raises(FinalDeliveryError, match="redaction"):
        parse_terminal_final_delivery([call], [result])


def test_rejects_ambiguous_current_turn(monkeypatch) -> None:
    call, result = _pair()
    duplicate = dict(result)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match="current_turn"):
        parse_terminal_final_delivery([call], [result, duplicate])


def test_candidate_gate_is_narrow_but_refusal_attempts_remain_visible() -> None:
    call, _result = _pair(background=True)
    assert is_terminal_final_delivery_candidate([call]) is True

    ordinary, _ordinary_result = _pair(command="printf ordinary")
    assert is_terminal_final_delivery_candidate([ordinary]) is False
