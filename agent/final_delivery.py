"""Qualification for terminal-owned exact final delivery.

Only one current-turn foreground invocation of the canonical ingest launcher
may produce a typed delivery. Every malformed or ambiguous candidate fails
closed before another model response can re-author the bytes.
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


def _parse_command(command: Any) -> list[str]:
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
    if any(token and all(character in ";&|><" for character in token) for token in tokens):
        raise FinalDeliveryError("allowlist: shell composition is forbidden")
    if len(tokens) < 2 or tokens[0] not in INGEST_LAUNCHER_ALIASES:
        raise FinalDeliveryError(
            "allowlist: command does not invoke the canonical ingest launcher"
        )
    return tokens


def is_terminal_final_delivery_candidate(tool_calls: Iterable[Any]) -> bool:
    """Detect canonical-launcher attempts broadly so malformed ones refuse."""
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
    return False


def _contains_required_contract(actual: Any, required: dict[str, Any]) -> bool:
    return isinstance(actual, dict) and all(
        key in actual
        and type(actual[key]) is type(value)
        and actual[key] == value
        for key, value in required.items()
    )


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


def _validated_terminal_stdout(
    tool_calls: Iterable[Any],
    tool_results: Iterable[dict[str, Any]],
    *,
    allowed_exit_codes: frozenset[int],
) -> tuple[str, int]:
    calls = list(tool_calls or [])
    results = list(tool_results or [])
    if len(calls) != 1:
        raise FinalDeliveryError("exactly_one: one substantive tool call is required")
    call = calls[0]
    if _function_attr(call, "name") != "terminal":
        raise FinalDeliveryError("tool_name: only terminal may activate exact delivery")

    arguments = _call_arguments(call)
    command = arguments.get("command")
    _parse_command(command)
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
        or exit_code not in allowed_exit_codes
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
    return stdout, exit_code


def parse_declared_intermediate_state(
    tool_calls: Iterable[Any],
    tool_results: Iterable[dict[str, Any]],
) -> str:
    """Return only an exact declared ingest continuation state/exit pair."""
    stdout, exit_code = _validated_terminal_stdout(
        tool_calls,
        tool_results,
        allowed_exit_codes=INGEST_CONTINUATION_EXIT_CODES,
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
    if pair not in INGEST_CONTINUATION_STATE_EXIT_CODES:
        raise FinalDeliveryError("contract: declared continuation pair is missing")
    return pair[0]


def parse_terminal_final_delivery(
    tool_calls: Iterable[Any],
    tool_results: Iterable[dict[str, Any]],
) -> FinalDelivery:
    """Return immutable exact bytes only when every current-turn gate passes."""
    stdout, _exit_code = _validated_terminal_stdout(
        tool_calls,
        tool_results,
        allowed_exit_codes=frozenset({0}),
    )

    envelope = _extract_envelope(stdout)
    if envelope.get("state") != "VERIFIED":
        raise FinalDeliveryError("contract: terminal state is not VERIFIED")
    if not _contains_required_contract(
        envelope.get("final_report_contract"), VERIFIED_FINAL_REPORT_CONTRACT
    ):
        raise FinalDeliveryError("contract: final_report_contract is invalid")
    if not _contains_required_contract(
        envelope.get("final_report_delivery_contract"),
        VERIFIED_DELIVERY_CONTRACT,
    ):
        raise FinalDeliveryError(
            "contract: final_report_delivery_contract is invalid"
        )

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
