"""Hermes-native terminal exact-delivery qualification.

This module is intentionally pure apart from the mandatory forced-redaction
check.  It accepts one current-turn terminal call/result pair and returns
immutable delivery bytes only when every exact-delivery invariant holds.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import shlex
from typing import Any, Iterable

from agent.redact import redact_terminal_output


INGEST_LAUNCHER = (
    "/Users/fisherivco/fisher/shared-state/skills-hub/skills/ingest/scripts/"
    "draft-first-run"
)
INGEST_LAUNCHER_ALIASES = frozenset({
    INGEST_LAUNCHER,
    "$HOME/fisher/shared-state/skills-hub/skills/ingest/scripts/draft-first-run",
    "${HOME}/fisher/shared-state/skills-hub/skills/ingest/scripts/draft-first-run",
})
INGEST_INTERMEDIATE_STATES = frozenset({
    "SUMMARY_REQUEST_READY",
    "SYNTHESIS_REQUEST_READY",
})
VERIFIED_FINAL_REPORT_CONTRACT = {
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
VERIFIED_DELIVERY_CONTRACT = {
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
    **VERIFIED_DELIVERY_CONTRACT,
    "version": "a054.material-blocked-report-delivery.v1",
    "terminal_state": "MATERIAL_BLOCKED_RETAINED",
}
TERMINAL_CONTRACTS = {
    "VERIFIED": (
        VERIFIED_FINAL_REPORT_CONTRACT,
        VERIFIED_DELIVERY_CONTRACT,
        0,
    ),
    "MATERIAL_BLOCKED_RETAINED": (
        MATERIAL_BLOCKED_FINAL_REPORT_CONTRACT,
        MATERIAL_BLOCKED_DELIVERY_CONTRACT,
        4,
    ),
}


class FinalDeliveryError(ValueError):
    """Raised when a purported exact-delivery result fails closed."""


def _contains_required_contract(
    actual: Any,
    required: dict[str, Any],
) -> bool:
    """Require every ratified invariant while permitting additive metadata."""
    return isinstance(actual, dict) and all(
        key in actual and actual[key] == value
        for key, value in required.items()
    )


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


def _parse_command(command: str) -> list[str]:
    if not isinstance(command, str) or not command.strip():
        raise FinalDeliveryError("allowlist: terminal command is missing")
    if "$(" in command or "`" in command or "\n" in command or "\r" in command:
        raise FinalDeliveryError("allowlist: shell substitution or line composition is forbidden")
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|><")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError as exc:
        raise FinalDeliveryError("allowlist: terminal command is malformed") from exc
    if any(token and all(ch in ";&|><" for ch in token) for token in tokens):
        raise FinalDeliveryError("allowlist: shell composition is forbidden")
    if len(tokens) < 2 or tokens[0] not in INGEST_LAUNCHER_ALIASES:
        raise FinalDeliveryError("allowlist: command does not invoke draft-first-run")
    return tokens


def _call_arguments(call: Any) -> dict[str, Any]:
    raw = _function_attr(call, "arguments")
    try:
        args = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise FinalDeliveryError("allowlist: terminal arguments are malformed") from exc
    if not isinstance(args, dict):
        raise FinalDeliveryError("allowlist: terminal arguments must be an object")
    return args


def is_terminal_final_delivery_candidate(tool_calls: Iterable[Any]) -> bool:
    """Return whether this turn attempts the canonical launcher lane.

    This is intentionally broader than qualification: background mode,
    multiple calls, and shell composition remain candidates so the strict
    parser can refuse them visibly instead of allowing a model fallback.
    """
    calls = list(tool_calls or [])
    for call in calls:
        if _function_attr(call, "name") != "terminal":
            continue
        try:
            args = _call_arguments(call)
            command = args.get("command")
            if not isinstance(command, str):
                continue
            tokens = shlex.split(command, posix=True)
        except (FinalDeliveryError, ValueError):
            continue
        if tokens and tokens[0] in INGEST_LAUNCHER_ALIASES:
            return True
    return False


def _extract_envelope(stdout: str) -> dict[str, Any]:
    if not isinstance(stdout, str) or not stdout:
        raise FinalDeliveryError("terminal_result: stdout is empty")
    candidates = [stdout]
    candidates.extend(line for line in reversed(stdout.splitlines()) if line.strip())
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict) and "final_report_delivery_contract" in parsed:
            return parsed
    raise FinalDeliveryError("terminal_result: verified final-report envelope missing")


def _validated_terminal_stdout(
    tool_calls: Iterable[Any],
    tool_results: Iterable[dict[str, Any]],
    *,
    allowed_exit_codes: frozenset[int] = frozenset({0}),
) -> tuple[str, int]:
    calls = list(tool_calls or [])
    results = list(tool_results or [])
    if len(calls) != 1:
        raise FinalDeliveryError("exactly_one: one substantive tool call is required")
    call = calls[0]
    if _function_attr(call, "name") != "terminal":
        raise FinalDeliveryError("tool_name: only terminal may activate exact delivery")

    args = _call_arguments(call)
    command = args.get("command")
    _parse_command(command)
    if args.get("background", False) is True:
        raise FinalDeliveryError("background: exact delivery requires foreground execution")

    call_id = _call_attr(call, "id")
    matching = [
        result for result in results
        if isinstance(result, dict) and result.get("tool_call_id") == call_id
    ]
    if len(matching) != 1:
        raise FinalDeliveryError("current_turn: matching terminal result missing or ambiguous")
    result = matching[0]
    if result.get("name") != "terminal" and result.get("tool_name") != "terminal":
        raise FinalDeliveryError("tool_name: result is not terminal output")
    content = result.get("content")
    try:
        wrapper = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise FinalDeliveryError("terminal_result: wrapper is malformed") from exc
    if not isinstance(wrapper, dict):
        raise FinalDeliveryError("terminal_result: wrapper must be an object")
    exit_code = wrapper.get("exit_code")
    if exit_code not in allowed_exit_codes or wrapper.get("error") is not None:
        raise FinalDeliveryError("terminal_result: terminal execution was not successful")
    stdout = wrapper.get("output")
    if not isinstance(stdout, str):
        raise FinalDeliveryError("terminal_result: stdout must be text")
    if redact_terminal_output(stdout, command, force=True) != stdout:
        raise FinalDeliveryError("redaction: forced redaction would alter terminal stdout")
    return stdout, exit_code


def parse_declared_intermediate_state(
    tool_calls: Iterable[Any],
    tool_results: Iterable[dict[str, Any]],
) -> str:
    """Return a public ingest midstate only for a strict current-turn pair.

    Any unknown, malformed, or report-bearing state fails closed so the caller
    can route it through terminal qualification and produce a visible refusal.
    """
    stdout, _exit_code = _validated_terminal_stdout(tool_calls, tool_results)
    candidates = [stdout]
    candidates.extend(line for line in reversed(stdout.splitlines()) if line.strip())
    envelope: dict[str, Any] | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            envelope = parsed
            break
    if envelope is None:
        raise FinalDeliveryError("terminal_result: ingest state envelope missing")

    state = envelope.get("state")
    if state not in INGEST_INTERMEDIATE_STATES:
        raise FinalDeliveryError("contract: declared intermediate state missing")
    forbidden_report_fields = {
        "final_report_message",
        "final_report_message_sha256",
        "final_report_contract",
        "final_report_delivery_contract",
    }
    if forbidden_report_fields.intersection(envelope):
        raise FinalDeliveryError(
            "contract: intermediate state carries terminal report fields"
        )
    return state


def parse_terminal_final_delivery(
    tool_calls: Iterable[Any],
    tool_results: Iterable[dict[str, Any]],
) -> FinalDelivery:
    stdout, exit_code = _validated_terminal_stdout(
        tool_calls,
        tool_results,
        allowed_exit_codes=frozenset({0, 4}),
    )

    envelope = _extract_envelope(stdout)
    state = envelope.get("state")
    contracts = TERMINAL_CONTRACTS.get(state)
    if contracts is None:
        raise FinalDeliveryError("contract: terminal state is not supported")
    (
        required_report_contract,
        required_delivery_contract,
        required_exit_code,
    ) = contracts
    if exit_code != required_exit_code:
        raise FinalDeliveryError(
            "contract: terminal state and exit status are inconsistent"
        )
    report_contract = envelope.get("final_report_contract")
    if not _contains_required_contract(
        report_contract, required_report_contract
    ):
        raise FinalDeliveryError("contract: final_report_contract invariants are invalid")
    delivery_contract = envelope.get("final_report_delivery_contract")
    if not _contains_required_contract(
        delivery_contract, required_delivery_contract
    ):
        raise FinalDeliveryError("contract: final_report_delivery_contract invariants are invalid")

    message = envelope.get("final_report_message")
    digest = envelope.get("final_report_message_sha256")
    if not isinstance(message, str) or not message.strip():
        raise FinalDeliveryError("contract: final_report_message is empty")
    if message.endswith(("\n", "\r")):
        raise FinalDeliveryError("contract: terminal newline is forbidden")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise FinalDeliveryError("contract: final_report_message SHA is malformed")
    computed = hashlib.sha256(message.encode("utf-8")).hexdigest()
    if digest != computed:
        raise FinalDeliveryError("contract: final_report_message SHA mismatch")
    return FinalDelivery(message=message, sha256=digest)
