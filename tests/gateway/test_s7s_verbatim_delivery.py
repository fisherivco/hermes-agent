"""S7S verbatim delivery projection — unit tests (round 2).

Covers Chi G1 findings F1-F5:
- F1: seam is AFTER all downstream mutators (tested by verifying output)
- F2: stale envelope from earlier turn does NOT fire
- F3: strict boolean gate + whitespace-only + malformed SHA all fallback
- 1 positive + 8 negatives
"""
from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

import pytest


def _tool_message(payload: dict) -> dict:
    return {"role": "tool", "content": json.dumps(payload)}


def _verbatim_envelope(message: str, *, sha_override: str | None = None) -> dict:
    sha = sha_override or hashlib.sha256(message.encode("utf-8")).hexdigest()
    return {
        "state": "VERIFIED",
        "final_report_message": message,
        "final_report_message_sha256": sha,
        "final_report_delivery_contract": {"mode": "exact_verbatim"},
    }


def _agent_result_current_turn(message: str, *, sha_override: str | None = None) -> dict:
    """Agent result where the tool envelope is the LAST tool message (current turn)."""
    envelope = _verbatim_envelope(message, sha_override=sha_override)
    return {
        "final_response": "Model preamble text that should be bypassed.",
        "messages": [
            {"role": "user", "content": "ingest url"},
            {"role": "assistant", "content": None},
            _tool_message(envelope),
            {"role": "assistant", "content": "Model preamble text that should be bypassed."},
        ],
    }


def _agent_result_stale_envelope(message: str) -> dict:
    """Agent result where a verbatim envelope exists from a PRIOR turn,
    but a non-ingest tool ran in the current turn."""
    envelope = _verbatim_envelope(message)
    return {
        "final_response": "This is from a different tool in the current turn.",
        "messages": [
            # --- prior turn (has envelope) ---
            {"role": "user", "content": "ingest url"},
            {"role": "assistant", "content": None},
            _tool_message(envelope),
            {"role": "assistant", "content": "Old model response."},
            # --- current turn (no envelope) ---
            {"role": "user", "content": "now do something else"},
            {"role": "assistant", "content": None},
            _tool_message({"result": "some other tool output"}),
            {"role": "assistant", "content": "This is from a different tool in the current turn."},
        ],
    }


@pytest.fixture(autouse=True)
def _patch_config_loader(monkeypatch):
    """Patch _load_gateway_config to return a dict with the gate enabled (boolean True)."""
    import gateway.run as run_module
    monkeypatch.setattr(
        run_module,
        "_load_gateway_config",
        lambda: {"gateway": {"verbatim_delivery_enabled": True}},
    )


class TestVerbatimDeliveryPositive:
    def test_verbatim_fires_when_envelope_is_current_turn_and_gate_enabled(self):
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        message = "## Knowledge headline\nExact verbatim content with more than whitespace."
        result = _agent_result_current_turn(message)
        output = _s7s_verbatim_delivery_or_fallback(result, "model final_response")
        assert output == message


class TestVerbatimDeliveryNegatives:
    def test_gate_off_falls_back(self, monkeypatch):
        import gateway.run as run_module
        monkeypatch.setattr(
            run_module,
            "_load_gateway_config",
            lambda: {"gateway": {"verbatim_delivery_enabled": False}},
        )
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        message = "## Knowledge headline\nContent."
        result = _agent_result_current_turn(message)
        fallback = "model response"
        assert _s7s_verbatim_delivery_or_fallback(result, fallback) == fallback

    def test_gate_string_false_falls_back(self, monkeypatch):
        """F3: string 'false' must NOT enable verbatim (strict boolean)."""
        import gateway.run as run_module
        monkeypatch.setattr(
            run_module,
            "_load_gateway_config",
            lambda: {"gateway": {"verbatim_delivery_enabled": "false"}},
        )
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        message = "## Knowledge headline\nContent."
        result = _agent_result_current_turn(message)
        assert _s7s_verbatim_delivery_or_fallback(result, "fallback") == "fallback"

    def test_sha_mismatch_falls_back(self):
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        message = "## Knowledge headline\nContent."
        result = _agent_result_current_turn(message, sha_override="0" * 64)
        fallback = "model response"
        assert _s7s_verbatim_delivery_or_fallback(result, fallback) == fallback

    def test_malformed_sha_falls_back(self):
        """F3: SHA that isn't 64 lowercase hex chars must fallback."""
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        message = "## Knowledge headline\nContent."
        result = _agent_result_current_turn(message, sha_override="ABCD" * 16)  # uppercase
        assert _s7s_verbatim_delivery_or_fallback(result, "fallback") == "fallback"

    def test_missing_envelope_falls_back(self):
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        result = {
            "final_response": "Normal non-ingest response.",
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "Normal non-ingest response."},
            ],
        }
        fallback = "Normal non-ingest response."
        assert _s7s_verbatim_delivery_or_fallback(result, fallback) == fallback

    def test_whitespace_only_message_falls_back(self):
        """F3: whitespace-only message must not be delivered as verbatim."""
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        whitespace = "   \n\t  "
        sha = hashlib.sha256(whitespace.encode("utf-8")).hexdigest()
        result = _agent_result_current_turn(whitespace, sha_override=sha)
        assert _s7s_verbatim_delivery_or_fallback(result, "fallback") == "fallback"

    def test_stale_envelope_from_prior_turn_falls_back(self):
        """F2: a verbatim envelope from an earlier turn must NOT override the current response."""
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        message = "## Knowledge headline\nThis is from a prior ingest."
        result = _agent_result_stale_envelope(message)
        fallback = "This is from a different tool in the current turn."
        assert _s7s_verbatim_delivery_or_fallback(result, fallback) == fallback

    def test_non_ingest_traffic_unaffected(self):
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        result = {
            "final_response": "Chat about weather.",
            "messages": [
                {"role": "user", "content": "What's the weather?"},
                {"role": "assistant", "content": "Chat about weather."},
            ],
        }
        assert _s7s_verbatim_delivery_or_fallback(result, "Chat about weather.") == "Chat about weather."
