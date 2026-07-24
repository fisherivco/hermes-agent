from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from agent.final_delivery import (
    FinalDeliveryError,
    parse_declared_intermediate_state,
    parse_terminal_final_delivery,
)


LAUNCHER = "/Users/fisherivco/fisher/shared-state/skills-hub/skills/ingest/scripts/draft-first-run"


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


def _material_blocked_envelope(
    message: str = "Material settlement retained",
) -> dict:
    material_report = {
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
    }
    return {
        "state": "MATERIAL_BLOCKED_RETAINED",
        "material_report": material_report,
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


def _semantic_correction_envelope() -> dict:
    return {
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
        "state": "SEMANTIC_CORRECTION_REQUIRED",
    }


def _pair(
    *,
    envelope=None,
    command=None,
    outer=None,
    background=False,
    exit_code=0,
):
    call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="terminal",
            arguments=json.dumps({
                "command": command or f"{LAUNCHER} https://example.test/source",
                "background": background,
            }),
        ),
    )
    payload = outer or {
        "output": json.dumps(envelope or _envelope()),
        "exit_code": exit_code,
        "error": None,
    }
    result = {
        "role": "tool",
        "name": "terminal",
        "tool_call_id": "call-1",
        "content": json.dumps(payload),
    }
    return call, result


def test_accepts_source_declared_semantic_correction_continuation(monkeypatch):
    call, result = _pair(
        envelope=_semantic_correction_envelope(),
        exit_code=5,
    )
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    assert parse_declared_intermediate_state([call], [result]) == (
        "SEMANTIC_CORRECTION_REQUIRED"
    )


def test_rejects_unknown_state_at_continue_class_exit_code(monkeypatch):
    envelope = _semantic_correction_envelope()
    envelope["state"] = "UNKNOWN_RETRY_READY"
    call, result = _pair(envelope=envelope, exit_code=5)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match="continuation state"):
        parse_declared_intermediate_state([call], [result])


@pytest.mark.parametrize(
    ("state", "exit_code"),
    [
        ("SUMMARY_REQUEST_READY", 5),
        ("SYNTHESIS_REQUEST_READY", 5),
        ("SEMANTIC_CORRECTION_REQUIRED", 0),
    ],
)
def test_rejects_continue_state_exit_code_mismatch(
    monkeypatch,
    state,
    exit_code,
):
    envelope = _semantic_correction_envelope()
    envelope["state"] = state
    envelope["rc"] = exit_code
    call, result = _pair(envelope=envelope, exit_code=exit_code)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match="continuation state"):
        parse_declared_intermediate_state([call], [result])


def test_rejects_semantic_correction_with_terminal_report_fields(monkeypatch):
    envelope = _semantic_correction_envelope()
    envelope["final_report_message"] = "must not be accepted"
    call, result = _pair(envelope=envelope, exit_code=5)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match="terminal report fields"):
        parse_declared_intermediate_state([call], [result])


def test_accepts_allowlisted_successful_foreground_current_turn(monkeypatch):
    call, result = _pair()
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )
    delivery = parse_terminal_final_delivery([call], [result])
    assert delivery.message == "## Exact report"
    assert delivery.sha256 == hashlib.sha256(delivery.message.encode()).hexdigest()


def test_accepts_material_blocked_terminal_contract(monkeypatch):
    call, result = _pair(
        envelope=_material_blocked_envelope(),
        exit_code=4,
    )
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )
    delivery = parse_terminal_final_delivery([call], [result])
    assert delivery.message == "Material settlement retained"
    assert delivery.sha256 == hashlib.sha256(
        delivery.message.encode()
    ).hexdigest()


def test_accepts_nonconflicting_additive_contract_metadata(monkeypatch):
    envelope = _envelope()
    envelope["final_report_contract"]["future_quality_receipt"] = "present"
    envelope["final_report_delivery_contract"]["future_transport_note"] = True
    call, result = _pair(envelope=envelope)
    monkeypatch.setattr("agent.final_delivery.redact_terminal_output", lambda text, command, force=False: text)
    assert parse_terminal_final_delivery([call], [result]).message == "## Exact report"


@pytest.mark.parametrize("launcher", [
    LAUNCHER,
    "$HOME/fisher/shared-state/skills-hub/skills/ingest/scripts/draft-first-run",
    "${HOME}/fisher/shared-state/skills-hub/skills/ingest/scripts/draft-first-run",
])
def test_accepts_only_canonical_launcher_spellings(monkeypatch, launcher):
    call, result = _pair(command=f'"{launcher}" "https://example.test/source?a=1&b=2"')
    monkeypatch.setattr("agent.final_delivery.redact_terminal_output", lambda text, command, force=False: text)
    assert parse_terminal_final_delivery([call], [result]).message == "## Exact report"


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (lambda c, r: setattr(c.function, "name", "web_search"), "tool_name"),
        (lambda c, r: setattr(c.function, "arguments", json.dumps({"command": "/tmp/draft-first-run x"})), "allowlist"),
        (lambda c, r: setattr(c.function, "arguments", json.dumps({"command": f"{LAUNCHER} x", "background": True})), "background"),
        (lambda c, r: r.update(tool_call_id="stale-call"), "current_turn"),
        (lambda c, r: r.update(content="not-json"), "terminal_result"),
    ],
)
def test_rejects_nonqualifying_tool_pairs(monkeypatch, mutator, reason):
    call, result = _pair()
    mutator(call, result)
    monkeypatch.setattr("agent.final_delivery.redact_terminal_output", lambda text, command, force=False: text)
    with pytest.raises(FinalDeliveryError, match=reason):
        parse_terminal_final_delivery([call], [result])


@pytest.mark.parametrize(
    "outer",
    [
        {"output": json.dumps(_envelope()), "exit_code": 1, "error": None},
        {"output": json.dumps(_envelope()), "exit_code": 0, "error": "failed"},
        {"output": "not-json", "exit_code": 0, "error": None},
    ],
)
def test_rejects_failed_or_malformed_terminal_wrapper(monkeypatch, outer):
    call, result = _pair(outer=outer)
    monkeypatch.setattr("agent.final_delivery.redact_terminal_output", lambda text, command, force=False: text)
    with pytest.raises(FinalDeliveryError):
        parse_terminal_final_delivery([call], [result])


@pytest.mark.parametrize(
    "change",
    [
        lambda e: e.update(state="PAIR_READY"),
        lambda e: e["final_report_contract"].update(delivery="model_copy"),
        lambda e: e["final_report_delivery_contract"].update(mode="formatted"),
        lambda e: e.update(final_report_message="   "),
        lambda e: e.update(final_report_message="has newline\n"),
        lambda e: e.update(final_report_message_sha256="0" * 64),
    ],
)
def test_rejects_invalid_exact_contract(monkeypatch, change):
    envelope = _envelope()
    change(envelope)
    call, result = _pair(envelope=envelope)
    monkeypatch.setattr("agent.final_delivery.redact_terminal_output", lambda text, command, force=False: text)
    with pytest.raises(FinalDeliveryError):
        parse_terminal_final_delivery([call], [result])


@pytest.mark.parametrize(
    ("contract_name", "field", "value"),
    [
        ("final_report_contract", "version", "wrong"),
        ("final_report_contract", "authoritative_field", "other"),
        ("final_report_contract", "sha256_field", "other_sha"),
        ("final_report_contract", "encoding", "utf-16"),
        ("final_report_contract", "normalization", "NFC"),
        ("final_report_contract", "terminal_newline", "allowed"),
        ("final_report_contract", "terminal_state", "MATERIAL_BLOCKED_RETAINED"),
        ("final_report_contract", "model_reauthoring_allowed", True),
        ("final_report_contract", "required_order", []),
        ("final_report_contract", "minimum_key_insights", 2),
        ("final_report_contract", "receipt_last", False),
        ("final_report_contract", "source_grounded", False),
        ("final_report_contract", "process_only_rejected", False),
        ("final_report_contract", "additive_only", False),
        ("final_report_contract", "success", False),
        ("final_report_delivery_contract", "version", "wrong"),
        ("final_report_delivery_contract", "authoritative_field", "other"),
        ("final_report_delivery_contract", "sha256_field", "other_sha"),
        ("final_report_delivery_contract", "encoding", "utf-16"),
        ("final_report_delivery_contract", "normalization", "NFC"),
        ("final_report_delivery_contract", "preamble_allowed", True),
        ("final_report_delivery_contract", "suffix_allowed", True),
        ("final_report_delivery_contract", "translation_allowed", True),
        ("final_report_delivery_contract", "reconstruction_allowed", True),
        ("final_report_delivery_contract", "terminal_newline", "allowed"),
    ],
)
def test_rejects_any_altered_public_contract_invariant(monkeypatch, contract_name, field, value):
    envelope = _envelope()
    envelope[contract_name][field] = value
    call, result = _pair(envelope=envelope)
    monkeypatch.setattr("agent.final_delivery.redact_terminal_output", lambda text, command, force=False: text)
    with pytest.raises(FinalDeliveryError, match="contract"):
        parse_terminal_final_delivery([call], [result])


@pytest.mark.parametrize(("contract_name", "field"), [
    ("final_report_contract", "version"),
    ("final_report_contract", "required_order"),
    ("final_report_contract", "success"),
    ("final_report_delivery_contract", "version"),
    ("final_report_delivery_contract", "terminal_newline"),
])
def test_rejects_missing_public_contract_invariant(monkeypatch, contract_name, field):
    envelope = _envelope()
    envelope[contract_name].pop(field)
    call, result = _pair(envelope=envelope)
    monkeypatch.setattr("agent.final_delivery.redact_terminal_output", lambda text, command, force=False: text)
    with pytest.raises(FinalDeliveryError, match="contract"):
        parse_terminal_final_delivery([call], [result])


@pytest.mark.parametrize("command", [
    f"{LAUNCHER} https://example.test/source $(touch /tmp/nope)",
    f"{LAUNCHER} https://example.test/source `touch /tmp/nope`",
    f"{LAUNCHER} https://example.test/source\nprintf nope",
    f"{LAUNCHER} https://example.test/source\rprintf nope",
])
def test_rejects_shell_substitution_and_line_composition(monkeypatch, command):
    call, result = _pair(command=command)
    monkeypatch.setattr("agent.final_delivery.redact_terminal_output", lambda text, command, force=False: text)
    with pytest.raises(FinalDeliveryError, match="allowlist"):
        parse_terminal_final_delivery([call], [result])


def test_rejects_when_forced_redaction_would_change_stdout(monkeypatch):
    call, result = _pair()
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text.replace("Exact", "[REDACTED]"),
    )
    with pytest.raises(FinalDeliveryError, match="redaction"):
        parse_terminal_final_delivery([call], [result])


def test_rejects_multiple_substantive_tool_calls(monkeypatch):
    call, result = _pair()
    other = SimpleNamespace(id="call-2", function=SimpleNamespace(name="read_file", arguments="{}"))
    monkeypatch.setattr("agent.final_delivery.redact_terminal_output", lambda text, command, force=False: text)
    with pytest.raises(FinalDeliveryError, match="exactly_one"):
        parse_terminal_final_delivery([call, other], [result])
