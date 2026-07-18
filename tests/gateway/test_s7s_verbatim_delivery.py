"""S7S verbatim delivery projection — unit tests.

5 negatives (fail-closed to current) + 1 positive (verbatim fires).
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


def _agent_result(message: str, *, sha_override: str | None = None) -> dict:
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


@pytest.fixture(autouse=True)
def _patch_config_loader(monkeypatch):
    """Patch _load_gateway_config to return a dict with the gate enabled."""
    import gateway.run as run_module
    monkeypatch.setattr(
        run_module,
        "_load_gateway_config",
        lambda: {"gateway": {"verbatim_delivery_enabled": True}},
    )


class TestVerbatimDeliveryPositive:
    def test_verbatim_fires_when_envelope_present_and_gate_enabled(self):
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        message = "## Knowledge headline\nExact verbatim content."
        result = _agent_result(message)
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
        result = _agent_result(message)
        fallback = "model response"
        assert _s7s_verbatim_delivery_or_fallback(result, fallback) == fallback

    def test_sha_mismatch_falls_back(self):
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        message = "## Knowledge headline\nContent."
        result = _agent_result(message, sha_override="0" * 64)
        fallback = "model response"
        assert _s7s_verbatim_delivery_or_fallback(result, fallback) == fallback

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

    def test_empty_message_falls_back(self):
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        envelope = _verbatim_envelope("")
        envelope["final_report_message"] = ""
        result = {
            "final_response": "model response",
            "messages": [_tool_message(envelope)],
        }
        assert _s7s_verbatim_delivery_or_fallback(result, "model response") == "model response"

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
