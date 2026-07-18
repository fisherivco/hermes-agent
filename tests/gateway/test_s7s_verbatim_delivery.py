"""S7S verbatim delivery projection — round 3 tests (typed bridge).

Chi's design: ExactDeliveryReply flows through base.py → adapter.
Acceptance: 5609-char report splits to N chunks whose join == original exactly.
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
    envelope = _verbatim_envelope(message, sha_override=sha_override)
    return {
        "final_response": "Model preamble that should be bypassed.",
        "messages": [
            {"role": "user", "content": "ingest url"},
            {"role": "assistant", "content": None},
            _tool_message(envelope),
            {"role": "assistant", "content": "Model preamble that should be bypassed."},
        ],
    }


def _agent_result_stale_envelope(message: str) -> dict:
    envelope = _verbatim_envelope(message)
    return {
        "final_response": "Current turn different tool.",
        "messages": [
            {"role": "user", "content": "ingest url"},
            {"role": "assistant", "content": None},
            _tool_message(envelope),
            {"role": "assistant", "content": "Old response."},
            {"role": "user", "content": "do something else"},
            {"role": "assistant", "content": None},
            _tool_message({"result": "other tool"}),
            {"role": "assistant", "content": "Current turn different tool."},
        ],
    }


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    import gateway.run as run_module
    monkeypatch.setattr(
        run_module, "_load_gateway_config",
        lambda: {"gateway": {"verbatim_delivery_enabled": True}},
    )


class TestTypedBridge:
    def test_returns_exact_delivery_reply_type(self):
        from gateway.platforms.base import ExactDeliveryReply
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        message = "## Knowledge headline\nExact content."
        result = _agent_result_current_turn(message)
        output = _s7s_verbatim_delivery_or_fallback(result, "fallback")
        assert isinstance(output, ExactDeliveryReply)
        assert str(output) == message
        assert output.declared_sha256 == hashlib.sha256(message.encode()).hexdigest()

    def test_split_only_raw_preserves_exact_bytes(self):
        """F1 acceptance: 5609-char report joins to exactly 5609."""
        from plugins.platforms.discord.adapter import DiscordAdapter

        # Generate a realistic 5609-char report
        report = "## Knowledge headline\n" + "x" * 100 + "\n\n"
        report += "## Core insight\n" + "Insight content. " * 50 + "\n\n"
        report += "## Key insights\n" + "- Insight line\n" * 80 + "\n"
        report += "## Value verdict\n" + "Tier A analysis. " * 30 + "\n\n"
        report += "## Allen AI OS / harness mapping\n" + "Adopt boundary. " * 40 + "\n\n"
        report += "## IVCO lens\n" + "Industry relevance. " * 30 + "\n\n"
        report += "## Caveats / limits\n" + "Source limits noted. " * 20 + "\n\n"
        report += "## Useful next actions (Do Now)\n" + "- Action item\n" * 10 + "\n"
        report += "## Defer\n- Deferred action\n\n"
        report += "## Verification receipt\n" + "VERIFIED; checks=10"
        # Pad to exactly 5609
        if len(report) < 5609:
            report += " " * (5609 - len(report))
        report = report[:5609]
        assert len(report) == 5609

        chunks = DiscordAdapter._split_only_raw(report, 2000)
        joined = "".join(chunks)
        assert joined == report
        assert len(joined) == 5609

    def test_safety_before_exact_blocks_credentials(self, monkeypatch):
        """F6: credential-shaped content fails closed."""
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        # Simulate a message containing credential-shaped data
        message = "## Report\nAPI key: sk-proj-ABCDEF123456 found in source.\n## End"
        result = _agent_result_current_turn(message)

        # Mock the redactor to simulate credential detection
        import gateway.run as run_module
        original_redact = run_module._redact_gateway_user_facing_secrets

        def mock_redact(text):
            return text.replace("sk-proj-ABCDEF123456", "***")

        monkeypatch.setattr(run_module, "_redact_gateway_user_facing_secrets", mock_redact)
        output = _s7s_verbatim_delivery_or_fallback(result, "fallback")
        assert output == "fallback"  # Fails closed

    def test_streaming_already_sent_falls_back(self):
        """F7: already_sent=True means streaming delivered — fallback."""
        from gateway.run import _s7s_verbatim_delivery_or_fallback

        message = "## Report\nContent."
        result = _agent_result_current_turn(message)
        result["already_sent"] = True
        assert _s7s_verbatim_delivery_or_fallback(result, "fallback") == "fallback"


class TestNegatives:
    def test_gate_off(self, monkeypatch):
        import gateway.run as run_module
        monkeypatch.setattr(run_module, "_load_gateway_config", lambda: {"gateway": {"verbatim_delivery_enabled": False}})
        from gateway.run import _s7s_verbatim_delivery_or_fallback
        assert _s7s_verbatim_delivery_or_fallback(_agent_result_current_turn("x" * 100), "fb") == "fb"

    def test_gate_string_false(self, monkeypatch):
        import gateway.run as run_module
        monkeypatch.setattr(run_module, "_load_gateway_config", lambda: {"gateway": {"verbatim_delivery_enabled": "false"}})
        from gateway.run import _s7s_verbatim_delivery_or_fallback
        assert _s7s_verbatim_delivery_or_fallback(_agent_result_current_turn("x" * 100), "fb") == "fb"

    def test_sha_mismatch(self):
        from gateway.run import _s7s_verbatim_delivery_or_fallback
        assert _s7s_verbatim_delivery_or_fallback(_agent_result_current_turn("content", sha_override="0" * 64), "fb") == "fb"

    def test_stale_envelope(self):
        from gateway.run import _s7s_verbatim_delivery_or_fallback
        assert _s7s_verbatim_delivery_or_fallback(_agent_result_stale_envelope("old content"), "fb") == "fb"

    def test_whitespace_only(self):
        from gateway.run import _s7s_verbatim_delivery_or_fallback
        ws = "   \n\t  "
        sha = hashlib.sha256(ws.encode()).hexdigest()
        assert _s7s_verbatim_delivery_or_fallback(_agent_result_current_turn(ws, sha_override=sha), "fb") == "fb"

    def test_no_envelope(self):
        from gateway.run import _s7s_verbatim_delivery_or_fallback
        result = {"final_response": "normal", "messages": [{"role": "assistant", "content": "normal"}]}
        assert _s7s_verbatim_delivery_or_fallback(result, "normal") == "normal"
