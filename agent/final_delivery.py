"""Qualification for terminal-owned exact final delivery.

Only one current-turn foreground invocation of a declared trusted launcher may
produce a typed delivery. Every malformed or ambiguous candidate fails closed
before another model response can re-author the bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shlex
from typing import Any, Iterable

from agent.redact import redact_terminal_output


INGEST_LAUNCHER_RELATIVE = (
    "fisher/shared-state/skills-hub/skills/ingest/scripts/draft-first-run"
)
INGEST_LAUNCHER_ALIASES = frozenset(
    {
        str(Path.home() / INGEST_LAUNCHER_RELATIVE),
        f"$HOME/{INGEST_LAUNCHER_RELATIVE}",
        f"${{HOME}}/{INGEST_LAUNCHER_RELATIVE}",
    }
)
YTS_WORKFLOW_RELATIVE = (
    "fisher/shared-state/skills-hub/skills/yts/scripts/yts_workflow.py"
)
YTS_WORKFLOW_ALIASES = frozenset({
    str(Path.home() / YTS_WORKFLOW_RELATIVE),
    f"$HOME/{YTS_WORKFLOW_RELATIVE}",
    f"${{HOME}}/{YTS_WORKFLOW_RELATIVE}",
})
YTS_PYTHON_ALIASES = frozenset({
    "python3",
    "/usr/bin/python3",
    "/opt/homebrew/bin/python3",
    str(Path.home() / ".hermes/hermes-agent/venv/bin/python"),
})

INGEST_PROFILE = "ingest"
YTS_START_PROFILE = "yts_start"
YTS_FINALIZE_PROFILE = "yts_finalize"

INGEST_CONTINUATION_STATE_EXIT_CODES = frozenset(
    {
        ("SUMMARY_REQUEST_READY", 0),
        ("SYNTHESIS_REQUEST_READY", 0),
        ("SEMANTIC_CORRECTION_REQUIRED", 5),
    }
)
INGEST_CONTINUATION_EXIT_CODES = frozenset(
    exit_code for _state, exit_code in INGEST_CONTINUATION_STATE_EXIT_CODES
)
YTS_CONTINUATION_STATE_EXIT_CODES = frozenset({
    ("ANALYSIS_REQUEST_READY", 0),
})
YTS_TERMINAL_STATE_EXIT_CODES = {
    YTS_START_PROFILE: frozenset({
        ("NO_TRANSCRIPT", 4),
        ("CAPTURE_FAILED", 5),
    }),
    YTS_FINALIZE_PROFILE: frozenset({
        ("VERIFIED", 0),
        ("DUPLICATE_VERIFIED", 0),
    }),
}

VERIFIED_FINAL_REPORT_CONTRACT_V2 = {
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
}

VERIFIED_FINAL_REPORT_CONTRACT_V3 = {
    **VERIFIED_FINAL_REPORT_CONTRACT_V2,
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

# Preserve the public v2 fixture API while the ingest producer and consumer
# migrate through an explicitly versioned compatibility window.
VERIFIED_FINAL_REPORT_CONTRACT = VERIFIED_FINAL_REPORT_CONTRACT_V2

VERIFIED_DELIVERY_CONTRACT_V2 = {
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
}

VERIFIED_DELIVERY_CONTRACT_V3 = {
    **VERIFIED_DELIVERY_CONTRACT_V2,
    "version": "a054.final-report-delivery.v3",
}

VERIFIED_DELIVERY_CONTRACT = VERIFIED_DELIVERY_CONTRACT_V2

FIRST_VALUE_DELIVERY_CONTRACT = {
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
}

MATERIAL_BLOCKED_FINAL_REPORT_CONTRACT = {
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
}

MATERIAL_BLOCKED_DELIVERY_CONTRACT = {
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
}

MATERIAL_BLOCK_REASONS = frozenset({
    "required_material_is_terminal",
    "required_material_recovery_unavailable",
    "material_recovery_ceiling_reached",
    "material_recovery_made_no_progress",
})

YTS_FINAL_REPORT_CONTRACT = {
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

YTS_DELIVERY_CONTRACT = {
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


class FinalDeliveryError(ValueError):
    """A candidate exact-delivery result failed qualification."""


@dataclass(frozen=True)
class FinalDelivery:
    message: str
    sha256: str

    def as_dict(self) -> dict[str, str]:
        return {"message": self.message, "sha256": self.sha256}


def _call_attr(call: Any, name: str, default: Any = None) -> Any:
    if isinstance(call, dict):
        return call.get(name, default)
    return getattr(call, name, default)


def _function_attr(call: Any, name: str, default: Any = None) -> Any:
    function = _call_attr(call, "function")
    if isinstance(function, dict):
        return function.get(name, default)
    return getattr(function, name, default)


def _call_arguments(call: Any) -> dict[str, Any]:
    try:
        arguments = json.loads(_function_attr(call, "arguments"))
    except (TypeError, ValueError) as exc:
        raise FinalDeliveryError("allowlist: terminal arguments are malformed") from exc
    if not isinstance(arguments, dict):
        raise FinalDeliveryError("allowlist: terminal arguments must be an object")
    return arguments


def _parse_command(command: Any) -> tuple[list[str], str]:
    if not isinstance(command, str) or not command.strip():
        raise FinalDeliveryError("allowlist: terminal command is missing")
    if "$(" in command or "`" in command or "\n" in command or "\r" in command:
        raise FinalDeliveryError(
            "allowlist: shell substitution or line composition is forbidden"
        )
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|><")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError as exc:
        raise FinalDeliveryError("allowlist: terminal command is malformed") from exc
    if any(
        token and all(character in ";&|><" for character in token) for token in tokens
    ):
        raise FinalDeliveryError("allowlist: shell composition is forbidden")
    if len(tokens) >= 2 and tokens[0] in INGEST_LAUNCHER_ALIASES:
        return tokens, INGEST_PROFILE
    if (
        len(tokens) >= 3
        and tokens[0] in YTS_PYTHON_ALIASES
        and tokens[1] in YTS_WORKFLOW_ALIASES
    ):
        if tokens[2] == "start":
            return tokens, YTS_START_PROFILE
        if tokens[2] == "finalize":
            return tokens, YTS_FINALIZE_PROFILE
        raise FinalDeliveryError("allowlist: unsupported YTS workflow command")
    raise FinalDeliveryError(
        "allowlist: command does not invoke a trusted terminal-delivery launcher"
    )


def is_terminal_final_delivery_candidate(tool_calls: Iterable[Any]) -> bool:
    """Detect trusted-launcher attempts broadly so malformed ones refuse."""
    for call in list(tool_calls or []):
        if _function_attr(call, "name") != "terminal":
            continue
        try:
            command = _call_arguments(call).get("command")
            tokens = shlex.split(command, posix=True)
        except (FinalDeliveryError, TypeError, ValueError):
            continue
        if tokens and tokens[0] in INGEST_LAUNCHER_ALIASES:
            return True
        if (
            len(tokens) >= 3
            and tokens[1] in YTS_WORKFLOW_ALIASES
            and tokens[2] in {"start", "finalize"}
        ):
            return True
    return False


def _contains_required_contract(actual: Any, required: dict[str, Any]) -> bool:
    return isinstance(actual, dict) and all(
        key in actual
        and type(actual[key]) is type(value)
        and actual[key] == value
        for key, value in required.items()
    )


def _verified_ingest_contracts(
    envelope: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    report = envelope.get("final_report_contract")
    delivery = envelope.get("final_report_delivery_contract")
    versions = (
        report.get("version") if isinstance(report, dict) else None,
        delivery.get("version") if isinstance(delivery, dict) else None,
    )
    if versions == (
        "a054.final-report.v2.verbatim",
        "a054.final-report-delivery.v2",
    ):
        return VERIFIED_FINAL_REPORT_CONTRACT_V2, VERIFIED_DELIVERY_CONTRACT_V2
    if versions == (
        "a054.final-report.v3.verbatim",
        "a054.final-report-delivery.v3",
    ):
        _validate_v3_completion(envelope)
        return VERIFIED_FINAL_REPORT_CONTRACT_V3, VERIFIED_DELIVERY_CONTRACT_V3
    raise FinalDeliveryError("contract: final-report contract versions are incompatible")


def _validate_v3_completion(envelope: dict[str, Any]) -> None:
    completion_status = envelope.get("completion_status")
    publication_status = envelope.get("publication_status")
    material_readiness = envelope.get("material_readiness")
    outstanding = envelope.get("outstanding_components")
    if (
        not isinstance(completion_status, str)
        or completion_status not in {"VERIFIED_COMPLETE", "VERIFIED_PARTIAL"}
        or publication_status != "VERIFIED"
        or not isinstance(material_readiness, str)
        or material_readiness not in {"COMPLETE", "PARTIAL"}
        or not isinstance(outstanding, list)
    ):
        raise FinalDeliveryError("contract: v3 completion fields are invalid")
    partial = bool(outstanding)
    if completion_status != (
        "VERIFIED_PARTIAL" if partial else "VERIFIED_COMPLETE"
    ) or material_readiness != ("PARTIAL" if partial else "COMPLETE"):
        raise FinalDeliveryError("contract: v3 completion fields disagree")

    component_lines: list[str] = []
    seen: set[str] = set()
    expected_actions = {
        "retryable": "retry_component_capture_without_root_refetch",
        "blocked": "review_component_capture_failure",
        "unavailable": "record_component_unavailable",
    }
    for item in outstanding:
        if not isinstance(item, dict) or set(item) != {
            "component_id",
            "kind",
            "source_status",
            "status",
            "next_action",
        }:
            raise FinalDeliveryError("contract: v3 completion component is invalid")
        component_id = item.get("component_id")
        kind = item.get("kind")
        source_status = item.get("source_status")
        status = item.get("status")
        next_action = item.get("next_action")
        if (
            not isinstance(component_id, str)
            or not component_id
            or component_id in seen
            or not isinstance(kind, str)
            or not kind
            or not isinstance(source_status, str)
            or source_status not in {"failed", "pending", "missing", "unsupported"}
            or not isinstance(status, str)
            or status not in expected_actions
            or next_action != expected_actions.get(status)
        ):
            raise FinalDeliveryError("contract: v3 completion component is invalid")
        seen.add(component_id)
        component_lines.append(f"- {component_id} [{kind}]: {status}")

    message = envelope.get("final_report_message")
    if not isinstance(message, str):
        raise FinalDeliveryError("contract: v3 completion message is invalid")
    expected_header = [
        f"Status: {completion_status}",
        "Publication: VERIFIED",
        f"Material readiness: {material_readiness}",
        f"Outstanding components: {len(outstanding)}",
        *(component_lines or ["- none"]),
    ]
    if message.splitlines()[4 : 4 + len(expected_header)] != expected_header:
        raise FinalDeliveryError("contract: v3 completion header disagrees")


def _validate_material_blocked(envelope: dict[str, Any]) -> None:
    report = envelope.get("material_report")
    if not isinstance(report, dict) or set(report) != {
        "state",
        "source_key",
        "draft_path",
        "counts",
        "blocked_components",
        "reason",
        "semantic_authoring_allowed",
        "next_action",
    }:
        raise FinalDeliveryError("contract: material report is invalid")
    source_key = report.get("source_key")
    draft_path = report.get("draft_path")
    reason = report.get("reason")
    next_action = report.get("next_action")
    for value in (source_key, draft_path, reason, next_action):
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or "\n" in value
            or "\r" in value
        ):
            raise FinalDeliveryError("contract: material report text is invalid")
    counts = report.get("counts")
    if not isinstance(counts, dict) or set(counts) != {
        "required",
        "complete",
        "pending_retryable",
        "terminal",
    }:
        raise FinalDeliveryError("contract: material counts are invalid")
    if any(type(counts[key]) is not int or counts[key] < 0 for key in counts):
        raise FinalDeliveryError("contract: material counts are invalid")
    required = counts["required"]
    complete = counts["complete"]
    pending = counts["pending_retryable"]
    terminal = counts["terminal"]
    blocked = report.get("blocked_components")
    if (
        required < 1
        or complete + pending + terminal != required
        or not isinstance(blocked, list)
        or not blocked
        or len(blocked) != pending + terminal
        or any(not isinstance(item, str) or not item for item in blocked)
        or len(set(blocked)) != len(blocked)
        or reason not in MATERIAL_BLOCK_REASONS
        or report.get("semantic_authoring_allowed") is not False
        or next_action != "retain_material_state_and_stop"
    ):
        raise FinalDeliveryError("contract: material report partition is invalid")
    for key in (
        "state",
        "source_key",
        "draft_path",
        "blocked_components",
        "reason",
        "semantic_authoring_allowed",
        "next_action",
    ):
        if envelope.get(key) != report.get(key):
            raise FinalDeliveryError("contract: material envelope disagrees")
    expected_message = (
        "Material settlement retained\n"
        "Status: MATERIAL_BLOCKED_RETAINED\n"
        f"Source Key: {source_key}\n"
        f"Draft: {draft_path}\n"
        f"Required material: {required}\n"
        f"Complete required material: {complete}\n"
        f"Pending retryable material: {pending}\n"
        f"Terminal material: {terminal}\n"
        f"Blocked components: {', '.join(blocked)}\n"
        f"Reason: {reason}\n"
        "Semantic authoring allowed: false\n"
        f"Next action: {next_action}"
    )
    if envelope.get("final_report_message") != expected_message:
        raise FinalDeliveryError("contract: material report message disagrees")


def _extract_envelope(stdout: str) -> dict[str, Any]:
    if not isinstance(stdout, str) or not stdout:
        raise FinalDeliveryError("terminal_result: stdout is empty")
    try:
        whole = json.loads(stdout)
    except (TypeError, ValueError):
        whole = None
    if isinstance(whole, dict) and "final_report_delivery_contract" in whole:
        return whole

    envelopes: list[dict[str, Any]] = []
    for candidate in stdout.splitlines():
        if not candidate.strip():
            continue
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict) and "final_report_delivery_contract" in parsed:
            envelopes.append(parsed)
    if not envelopes:
        raise FinalDeliveryError(
            "terminal_result: verified final-report envelope is missing"
        )
    if len(envelopes) != 1:
        raise FinalDeliveryError(
            "terminal_result: final-report envelope is ambiguous"
        )
    return envelopes[0]


def _extract_first_value_envelope(stdout: str) -> dict[str, Any] | None:
    if not isinstance(stdout, str) or not stdout:
        raise FinalDeliveryError("terminal_result: stdout is empty")
    candidates: list[dict[str, Any]] = []
    try:
        whole = json.loads(stdout)
    except (TypeError, ValueError):
        whole = None
    values = [whole] if isinstance(whole, dict) else []
    if not values:
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                values.append(parsed)
    for value in values:
        if (
            value.get("state") == "FIRST_VALUE_READY"
            or "first_value_report_delivery_contract" in value
        ):
            candidates.append(value)
    if not candidates:
        return None
    if len(candidates) != 1:
        raise FinalDeliveryError(
            "terminal_result: first-value envelope is ambiguous"
        )
    return candidates[0]


def _validated_terminal_stdout(
    tool_calls: Iterable[Any],
    tool_results: Iterable[dict[str, Any]],
    *,
    allowed_profiles: frozenset[str],
    allowed_exit_codes: dict[str, frozenset[int]],
) -> tuple[str, int, str]:
    calls = list(tool_calls or [])
    results = list(tool_results or [])
    if len(calls) != 1:
        raise FinalDeliveryError("exactly_one: one substantive tool call is required")
    call = calls[0]
    if _function_attr(call, "name") != "terminal":
        raise FinalDeliveryError("tool_name: only terminal may activate exact delivery")

    arguments = _call_arguments(call)
    command = arguments.get("command")
    _tokens, profile = _parse_command(command)
    if profile not in allowed_profiles:
        raise FinalDeliveryError("allowlist: launcher profile is not valid here")
    background = arguments.get("background", False)
    if not isinstance(background, bool) or background:
        raise FinalDeliveryError(
            "background: exact delivery requires foreground execution"
        )

    call_id = _call_attr(call, "id")
    if not isinstance(call_id, str) or not call_id:
        raise FinalDeliveryError("current_turn: terminal call identity is missing")
    matching_results = [
        result
        for result in results
        if isinstance(result, dict) and result.get("tool_call_id") == call_id
    ]
    if len(matching_results) != 1:
        raise FinalDeliveryError(
            "current_turn: matching terminal result is missing or ambiguous"
        )
    result = matching_results[0]
    if result.get("name") != "terminal" and result.get("tool_name") != "terminal":
        raise FinalDeliveryError("tool_name: result is not terminal output")

    try:
        wrapper = json.loads(result.get("content"))
    except (TypeError, ValueError) as exc:
        raise FinalDeliveryError("terminal_result: wrapper is malformed") from exc
    if not isinstance(wrapper, dict):
        raise FinalDeliveryError("terminal_result: wrapper must be an object")
    exit_code = wrapper.get("exit_code")
    if (
        type(exit_code) is not int
        or exit_code not in allowed_exit_codes[profile]
        or wrapper.get("error") is not None
    ):
        raise FinalDeliveryError(
            "terminal_result: terminal execution was not successful"
        )
    stdout = wrapper.get("output")
    if not isinstance(stdout, str):
        raise FinalDeliveryError("terminal_result: stdout must be text")
    if redact_terminal_output(stdout, command, force=True) != stdout:
        raise FinalDeliveryError(
            "redaction: forced redaction would alter terminal stdout"
        )
    return stdout, exit_code, profile


def parse_declared_intermediate_state(
    tool_calls: Iterable[Any],
    tool_results: Iterable[dict[str, Any]],
) -> str:
    """Return only an exact declared ingest continuation state/exit pair."""
    stdout, exit_code, profile = _validated_terminal_stdout(
        tool_calls,
        tool_results,
        allowed_profiles=frozenset({INGEST_PROFILE, YTS_START_PROFILE}),
        allowed_exit_codes={
            INGEST_PROFILE: INGEST_CONTINUATION_EXIT_CODES,
            YTS_START_PROFILE: frozenset({0}),
        },
    )
    try:
        whole = json.loads(stdout)
    except (TypeError, ValueError):
        whole = None
    envelopes: list[dict[str, Any]] = []
    if isinstance(whole, dict):
        envelopes.append(whole)
    else:
        candidates = (line for line in stdout.splitlines() if line.strip())
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                envelopes.append(parsed)
    if not envelopes:
        raise FinalDeliveryError("terminal_result: ingest state envelope is missing")

    terminal_report_fields = {
        "final_report_message",
        "final_report_message_sha256",
        "final_report_contract",
        "final_report_delivery_contract",
    }
    if any(terminal_report_fields.intersection(item) for item in envelopes):
        raise FinalDeliveryError(
            "contract: continuation output carries terminal report fields"
        )

    envelope = envelopes[-1]
    pair = (envelope.get("state"), exit_code)
    allowed_pairs = (
        INGEST_CONTINUATION_STATE_EXIT_CODES
        if profile == INGEST_PROFILE
        else YTS_CONTINUATION_STATE_EXIT_CODES
    )
    if pair not in allowed_pairs:
        raise FinalDeliveryError("contract: declared continuation pair is missing")
    return pair[0]


def parse_first_value_delivery(
    tool_calls: Iterable[Any],
    tool_results: Iterable[dict[str, Any]],
) -> FinalDelivery | None:
    """Return exact first-value bytes, or None when this is another ingest state."""
    stdout, exit_code, profile = _validated_terminal_stdout(
        tool_calls,
        tool_results,
        allowed_profiles=frozenset({
            INGEST_PROFILE,
            YTS_START_PROFILE,
            YTS_FINALIZE_PROFILE,
        }),
        allowed_exit_codes={
            INGEST_PROFILE: INGEST_CONTINUATION_EXIT_CODES | frozenset({0, 4}),
            YTS_START_PROFILE: frozenset({0, 4, 5}),
            YTS_FINALIZE_PROFILE: frozenset({0}),
        },
    )
    if profile != INGEST_PROFILE:
        return None
    envelope = _extract_first_value_envelope(stdout)
    if envelope is None:
        return None
    if exit_code != 0:
        raise FinalDeliveryError("first-value: terminal profile is invalid")
    if envelope.get("state") != "FIRST_VALUE_READY":
        raise FinalDeliveryError("first-value: terminal state is invalid")
    if envelope.get("readiness") not in {"READY_FULL", "READY_PARTIAL"}:
        raise FinalDeliveryError("first-value: readiness is invalid")
    if envelope.get("first_value_report_integrity") != "RUNNER_VERIFIED":
        raise FinalDeliveryError("first-value: integrity status is invalid")
    if envelope.get("first_value_report_delivery_contract") != FIRST_VALUE_DELIVERY_CONTRACT:
        raise FinalDeliveryError("first-value: delivery contract is invalid")
    message = envelope.get("first_value_report_message")
    digest = envelope.get("first_value_report_message_sha256")
    if (
        not isinstance(message, str)
        or not message.strip()
        or message.endswith(("\n", "\r"))
    ):
        raise FinalDeliveryError("first-value: report message is invalid")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise FinalDeliveryError("first-value: report SHA is malformed")
    try:
        computed = hashlib.sha256(message.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        raise FinalDeliveryError("first-value: report is not valid UTF-8") from exc
    if digest != computed:
        raise FinalDeliveryError("first-value: report SHA mismatch")
    return FinalDelivery(message=message, sha256=digest)


def parse_terminal_final_delivery(
    tool_calls: Iterable[Any],
    tool_results: Iterable[dict[str, Any]],
) -> FinalDelivery:
    """Return immutable exact bytes only when every current-turn gate passes."""
    stdout, exit_code, profile = _validated_terminal_stdout(
        tool_calls,
        tool_results,
        allowed_profiles=frozenset({
            INGEST_PROFILE,
            YTS_START_PROFILE,
            YTS_FINALIZE_PROFILE,
        }),
        allowed_exit_codes={
            INGEST_PROFILE: frozenset({0, 4}),
            YTS_START_PROFILE: frozenset({4, 5}),
            YTS_FINALIZE_PROFILE: frozenset({0}),
        },
    )

    envelope = _extract_envelope(stdout)
    if profile == INGEST_PROFILE:
        state_exit = (envelope.get("state"), exit_code)
        if state_exit == ("VERIFIED", 0):
            report_contract, delivery_contract = _verified_ingest_contracts(envelope)
        elif state_exit == ("MATERIAL_BLOCKED_RETAINED", 4):
            _validate_material_blocked(envelope)
            report_contract = MATERIAL_BLOCKED_FINAL_REPORT_CONTRACT
            delivery_contract = MATERIAL_BLOCKED_DELIVERY_CONTRACT
        else:
            raise FinalDeliveryError("contract: ingest terminal state/exit pair is invalid")
    else:
        if (
            envelope.get("state"),
            exit_code,
        ) not in YTS_TERMINAL_STATE_EXIT_CODES[profile]:
            raise FinalDeliveryError(
                "contract: YTS terminal state/exit pair is invalid"
            )
        report_contract = YTS_FINAL_REPORT_CONTRACT
        delivery_contract = YTS_DELIVERY_CONTRACT
    if not _contains_required_contract(
        envelope.get("final_report_contract"), report_contract
    ):
        raise FinalDeliveryError("contract: final_report_contract is invalid")
    if not _contains_required_contract(
        envelope.get("final_report_delivery_contract"), delivery_contract
    ):
        raise FinalDeliveryError("contract: final_report_delivery_contract is invalid")

    message = envelope.get("final_report_message")
    digest = envelope.get("final_report_message_sha256")
    if (
        not isinstance(message, str)
        or not message.strip()
        or message.endswith(("\n", "\r"))
    ):
        raise FinalDeliveryError("contract: final_report_message is invalid")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise FinalDeliveryError("contract: final_report_message SHA is malformed")
    try:
        encoded_message = message.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise FinalDeliveryError(
            "contract: final_report_message is not valid UTF-8"
        ) from exc
    computed = hashlib.sha256(encoded_message).hexdigest()
    if digest != computed:
        raise FinalDeliveryError("contract: final_report_message SHA mismatch")
    return FinalDelivery(message=message, sha256=digest)
