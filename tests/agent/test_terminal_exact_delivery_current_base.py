"""Fail-closed qualification for current-turn terminal exact delivery."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from agent import final_delivery as final_delivery_module
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


def _v3_envelope(*, partial: bool = False) -> dict:
    outstanding = (
        [
            {
                "component_id": "video_asr:1",
                "kind": "video",
                "source_status": "failed",
                "status": "retryable",
                "next_action": "retry_component_capture_without_root_refetch",
            }
        ]
        if partial
        else []
    )
    completion_status = "VERIFIED_PARTIAL" if partial else "VERIFIED_COMPLETE"
    material_readiness = "PARTIAL" if partial else "COMPLETE"
    component_lines = (
        "- video_asr:1 [video]: retryable" if partial else "- none"
    )
    message = (
        "Ingested: Example\n"
        "Tier: B\n"
        "Knowledge: memory/knowledge/example.md\n"
        "Source Final: memory/inbox/raw/example.md\n"
        f"Status: {completion_status}\n"
        "Publication: VERIFIED\n"
        f"Material readiness: {material_readiness}\n"
        f"Outstanding components: {len(outstanding)}\n"
        f"{component_lines}\n\n"
        "## Exact report"
    )
    envelope = _envelope(message)
    envelope.update(
        {
            "completion_status": completion_status,
            "publication_status": "VERIFIED",
            "material_readiness": material_readiness,
            "outstanding_components": outstanding,
        }
    )
    envelope["final_report_contract"].update(
        {
            "version": "a054.final-report.v3.verbatim",
            "integrity_status": "RUNNER_VERIFIED",
            "agent_digest_verification_required": False,
            "visible_reply": "DIRECT_FIELD_ONLY",
            "preamble_allowed": False,
            "suffix_allowed": False,
            "explanation_allowed": False,
            "completion_fields": [
                "completion_status",
                "publication_status",
                "material_readiness",
                "outstanding_components",
            ],
        }
    )
    envelope["final_report_delivery_contract"]["version"] = (
        "a054.final-report-delivery.v3"
    )
    return envelope


def _first_value_envelope() -> dict:
    message = (
        "Source Note Draft ready (READY_FULL)\n"
        "Source: memory/inbox/example.md\n"
        "Summary: grounded first value"
    )
    return {
        "state": "FIRST_VALUE_READY",
        "readiness": "READY_FULL",
        "first_value_report_message": message,
        "first_value_report_message_sha256": hashlib.sha256(
            message.encode("utf-8")
        ).hexdigest(),
        "first_value_report_integrity": "RUNNER_VERIFIED",
        "first_value_report_delivery_contract": {
            "version": "ingest.first-value-report.v2.direct",
            "authoritative_field": "first_value_report_message",
            "integrity_field": "first_value_report_message_sha256",
            "integrity_status": "RUNNER_VERIFIED",
            "agent_digest_verification_required": False,
            "visible_reply": "DIRECT_FIELD_ONLY",
            "preamble_allowed": False,
            "suffix_allowed": False,
            "explanation_allowed": False,
            "post_delivery_visible_text_allowed": False,
        },
    }


def _material_blocked_envelope() -> dict:
    message = (
        "Material settlement retained\n"
        "Status: MATERIAL_BLOCKED_RETAINED\n"
        "Source Key: src_test\n"
        "Draft: memory/inbox/example.md\n"
        "Required material: 2\n"
        "Complete required material: 1\n"
        "Pending retryable material: 0\n"
        "Terminal material: 1\n"
        "Blocked components: video_asr:1\n"
        "Reason: required_material_is_terminal\n"
        "Semantic authoring allowed: false\n"
        "Next action: retain_material_state_and_stop"
    )
    material_report = {
        "state": "MATERIAL_BLOCKED_RETAINED",
        "source_key": "src_test",
        "draft_path": "memory/inbox/example.md",
        "counts": {
            "required": 2,
            "complete": 1,
            "pending_retryable": 0,
            "terminal": 1,
        },
        "blocked_components": ["video_asr:1"],
        "reason": "required_material_is_terminal",
        "semantic_authoring_allowed": False,
        "next_action": "retain_material_state_and_stop",
    }
    return {
        **material_report,
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
            "integrity_status": "RUNNER_VERIFIED",
            "agent_digest_verification_required": False,
            "visible_reply": "DIRECT_FIELD_ONLY",
            "preamble_allowed": False,
            "suffix_allowed": False,
            "explanation_allowed": False,
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
        "final_report_message": message,
        "final_report_message_sha256": hashlib.sha256(
            message.encode("utf-8")
        ).hexdigest(),
    }


def _pair(
    *,
    envelope: dict | None = None,
    command: str | None = None,
    background: bool = False,
    exit_code: int = 0,
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
            {"output": output, "exit_code": exit_code, "error": None}
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


def test_accepts_first_value_checkpoint_before_continuation(monkeypatch) -> None:
    envelope = _first_value_envelope()
    call, result = _pair(envelope=envelope)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    delivery = final_delivery_module.parse_first_value_delivery([call], [result])

    assert delivery is not None
    assert delivery.message == envelope["first_value_report_message"]


def test_rejects_first_value_checkpoint_with_mismatched_sha(monkeypatch) -> None:
    envelope = _first_value_envelope()
    envelope["first_value_report_message_sha256"] = "0" * 64
    call, result = _pair(envelope=envelope)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match="first-value"):
        final_delivery_module.parse_first_value_delivery([call], [result])


def test_accepts_material_blocked_retained_as_exact_terminal_report(
    monkeypatch,
) -> None:
    envelope = _material_blocked_envelope()
    call, result = _pair(envelope=envelope, exit_code=4)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    assert final_delivery_module.parse_first_value_delivery([call], [result]) is None
    delivery = parse_terminal_final_delivery([call], [result])

    assert delivery.message == envelope["final_report_message"]


@pytest.mark.parametrize("exit_code", [0, 5])
def test_rejects_material_blocked_retained_with_wrong_exit(
    monkeypatch,
    exit_code: int,
) -> None:
    call, result = _pair(
        envelope=_material_blocked_envelope(),
        exit_code=exit_code,
    )
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError):
        parse_terminal_final_delivery([call], [result])


def test_rejects_material_blocked_report_that_disagrees_with_envelope(
    monkeypatch,
) -> None:
    envelope = _material_blocked_envelope()
    envelope["material_report"]["blocked_components"] = ["different:1"]
    call, result = _pair(envelope=envelope, exit_code=4)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match="material"):
        parse_terminal_final_delivery([call], [result])


@pytest.mark.parametrize("partial", [False, True])
def test_accepts_v3_completion_envelope(monkeypatch, partial: bool) -> None:
    envelope = _v3_envelope(partial=partial)
    call, result = _pair(envelope=envelope)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    delivery = parse_terminal_final_delivery([call], [result])

    assert delivery.message == envelope["final_report_message"]


def test_rejects_v3_completion_header_that_disagrees_with_payload(
    monkeypatch,
) -> None:
    envelope = _v3_envelope(partial=True)
    message = envelope["final_report_message"].replace(
        "Status: VERIFIED_PARTIAL", "Status: VERIFIED_COMPLETE"
    )
    envelope["final_report_message"] = message
    envelope["final_report_message_sha256"] = hashlib.sha256(
        message.encode("utf-8")
    ).hexdigest()
    call, result = _pair(envelope=envelope)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match="completion"):
        parse_terminal_final_delivery([call], [result])


def test_rejects_v3_unhashable_completion_status_fail_closed(monkeypatch) -> None:
    envelope = _v3_envelope(partial=True)
    envelope["outstanding_components"][0]["status"] = []
    call, result = _pair(envelope=envelope)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match="completion"):
        parse_terminal_final_delivery([call], [result])


def test_rejects_v3_unhashable_completion_summary_fail_closed(monkeypatch) -> None:
    envelope = _v3_envelope(partial=True)
    envelope["completion_status"] = []
    call, result = _pair(envelope=envelope)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match="completion"):
        parse_terminal_final_delivery([call], [result])


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
        (
            lambda call, result: setattr(
                call.function,
                "arguments",
                json.dumps(
                    {
                        "command": f'"{LAUNCHER}" "https://example.test/source"',
                        "background": "true",
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
        lambda envelope: envelope["final_report_delivery_contract"].update(
            preamble_allowed=0
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


def test_rejects_missing_call_identity_even_if_result_identity_is_missing(
    monkeypatch,
) -> None:
    call, result = _pair()
    call.id = None
    result["tool_call_id"] = None
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match="current_turn"):
        parse_terminal_final_delivery([call], [result])


def test_rejects_boolean_exit_code(monkeypatch) -> None:
    call, result = _pair()
    wrapper = json.loads(result["content"])
    wrapper["exit_code"] = False
    result["content"] = json.dumps(wrapper)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match="terminal_result"):
        parse_terminal_final_delivery([call], [result])


def test_rejects_non_utf8_scalar_message(monkeypatch) -> None:
    envelope = _envelope()
    envelope["final_report_message"] = "\ud800"
    envelope["final_report_message_sha256"] = "0" * 64
    call, result = _pair(envelope=envelope)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match="UTF-8"):
        parse_terminal_final_delivery([call], [result])


def test_rejects_multiple_final_envelopes_in_one_terminal_stdout(
    monkeypatch,
) -> None:
    call, result = _pair()
    wrapper = json.loads(result["content"])
    wrapper["output"] = "\n".join(
        (
            json.dumps({"state": "SUMMARY_READY"}),
            json.dumps(_envelope("first payload")),
            json.dumps(_envelope("second payload")),
        )
    )
    result["content"] = json.dumps(wrapper)
    monkeypatch.setattr(
        "agent.final_delivery.redact_terminal_output",
        lambda text, command, force=False: text,
    )

    with pytest.raises(FinalDeliveryError, match="ambiguous"):
        parse_terminal_final_delivery([call], [result])


def test_candidate_gate_is_narrow_but_refusal_attempts_remain_visible() -> None:
    call, _result = _pair(background=True)
    assert is_terminal_final_delivery_candidate([call]) is True

    ordinary, _ordinary_result = _pair(command="printf ordinary")
    assert is_terminal_final_delivery_candidate([ordinary]) is False
